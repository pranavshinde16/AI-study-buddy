"""LLMOps metrics computed from the logs the app already writes (IMPLEMENTATION_PLAN §7.2, Phase 11).

Sources:
    llm_calls      one row per request sent to a model (LLM, ASR, embedding)  -> M2, M3, M5, errors, prompts
    pipeline_runs  one row per pipeline stage (transcribing has audio_sec)    -> M1 (real-time factor)
    qa_logs        one row per /ask or /chat question                         -> M4, refusal split

Every number is computed from those rows at request time; nothing is stored or estimated.
Filters: a date range (UTC days, inclusive), a task and a generator. Evaluation traffic
(tasks starting with "eval_") is excluded from the live-traffic metrics unless asked for.

Percentiles use linear interpolation between the closest ranks (the same as numpy's default),
computed in Python so the results are identical on SQLite (tests) and PostgreSQL.
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.chat import QALog
from app.models.lecture import Lecture
from app.models.llmops import LLMCall, PipelineRun
from app.services.llm.generators import GeneratorRegistry
from app.services.llm.pricing import PricingTable

EVAL_TASK_PREFIX = "eval_"
OK = "ok"
JSON_INVALID = "json_invalid"
FAILED = frozenset({"error", "unavailable", "rate_limited", "not_configured"})
TRANSCRIBING = "transcribing"
ASR_TASK = "asr"
REFUSAL_REASONS = ("below_threshold", "not_in_chunks")


# ---------------------------------------------------------------------------- helpers


def percentile(values: Sequence[float], q: float) -> float | None:
    """q in [0, 100]; linear interpolation between closest ranks. None for no data."""
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    if len(data) == 1:
        return float(data[0])
    pos = (len(data) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return float(data[lo] + (data[hi] - data[lo]) * (pos - lo))


def latency_stats(values: Iterable[float | None]) -> dict[str, Any]:
    vals = [float(v) for v in values if v is not None]
    return {
        "n": len(vals),
        "p50_ms": _r(percentile(vals, 50)),
        "p95_ms": _r(percentile(vals, 95)),
        "mean_ms": _r(sum(vals) / len(vals)) if vals else None,
    }


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(x, nd)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _sum_or_none(values: Iterable[float | None]) -> tuple[float, int]:
    """(sum of known values, number of unknown ones)."""
    total, unknown = 0.0, 0
    for v in values:
        if v is None:
            unknown += 1
        else:
            total += v
    return round(total, 8), unknown


@dataclass(frozen=True)
class MetricFilter:
    date_from: date | None = None
    date_to: date | None = None  # inclusive
    task: str | None = None
    generator: str | None = None
    include_eval: bool = False

    def bounds(self) -> tuple[datetime | None, datetime | None]:
        start = datetime.combine(self.date_from, time.min, tzinfo=UTC) if self.date_from else None
        end = datetime.combine(self.date_to + timedelta(days=1), time.min, tzinfo=UTC) if self.date_to else None
        return start, end

    def as_dict(self) -> dict[str, Any]:
        return {"date_from": self.date_from, "date_to": self.date_to, "task": self.task,
                "generator": self.generator, "include_eval": self.include_eval}


class LlmOpsMetrics:
    def __init__(self, db: Session, pricing: PricingTable, generators: GeneratorRegistry) -> None:
        self.db = db
        self.pricing = pricing
        self.generators = generators
        self._asr_cache: dict[uuid.UUID, tuple[str, str]] | None = None

    # ------------------------------------------------------------------ row loaders

    def _calls_query(self, f: MetricFilter) -> Select:
        q = select(LLMCall)
        start, end = f.bounds()
        if start:
            q = q.where(LLMCall.ts >= start)
        if end:
            q = q.where(LLMCall.ts < end)
        if f.task:
            q = q.where(LLMCall.task == f.task)
        elif not f.include_eval:
            q = q.where(~LLMCall.task.startswith(EVAL_TASK_PREFIX))
        if f.generator:
            g = self.generators.get(f.generator)  # 422 UNKNOWN_GENERATOR for a bad name
            q = q.where(LLMCall.provider == g.provider, LLMCall.model == g.model)
        return q

    def calls(self, f: MetricFilter) -> list[LLMCall]:
        return list(self.db.scalars(self._calls_query(f).order_by(LLMCall.ts)))

    def qa_rows(self, f: MetricFilter) -> list[QALog]:
        q = select(QALog)
        start, end = f.bounds()
        if start:
            q = q.where(QALog.created_at >= start)
        if end:
            q = q.where(QALog.created_at < end)
        if f.generator:
            q = q.where(QALog.generator == f.generator)
        return list(self.db.scalars(q.order_by(QALog.created_at)))

    def transcription_runs(self, f: MetricFilter) -> list[tuple[PipelineRun, str | None]]:
        q = (select(PipelineRun, Lecture.title).join(Lecture, Lecture.id == PipelineRun.lecture_id, isouter=True)
             .where(PipelineRun.stage == TRANSCRIBING, PipelineRun.status == OK))
        start, end = f.bounds()
        if start:
            q = q.where(PipelineRun.started_at >= start)
        if end:
            q = q.where(PipelineRun.started_at < end)
        return [(run, title) for run, title in self.db.execute(q.order_by(PipelineRun.started_at)).all()]

    def _asr_in_scope(self, f: MetricFilter) -> bool:
        """ASR equivalent cost comes from pipeline_runs (audio length), not from llm_calls."""
        return f.generator is None and f.task in (None, ASR_TASK)

    # ------------------------------------------------------------------ costs

    def _equivalent(self, c: LLMCall) -> float | None:
        if c.task == ASR_TASK:
            return None  # priced per audio minute from pipeline_runs, see _asr_equivalent
        if c.status != OK and c.status != JSON_INVALID:
            return 0.0  # a failed request returned no tokens
        if c.provider == "local" or c.provider == "ollama":
            return 0.0
        return self.pricing.equivalent_cost(c.provider, c.model, c.input_tokens, c.output_tokens)

    def _asr_models(self) -> dict[uuid.UUID, tuple[str, str]]:
        """lecture -> (provider, model) of its successful ASR requests (what really transcribed it)."""
        if self._asr_cache is None:
            rows = self.db.execute(select(LLMCall.lecture_id, LLMCall.provider, LLMCall.model)
                                   .where(LLMCall.task == ASR_TASK, LLMCall.status == OK)
                                   .order_by(LLMCall.ts)).all()
            self._asr_cache = {lec: (p, m) for lec, p, m in rows if lec is not None}
        return self._asr_cache

    def _asr_equivalent(self, run: PipelineRun) -> float | None:
        """Speech-to-text priced per audio minute (pricing.yaml audio_models). None when the
        lecture has no ASR log row or the model has no listed price."""
        pm = self._asr_models().get(run.lecture_id)
        if pm is None:
            return None
        return self.pricing.equivalent_audio_cost(pm[0], pm[1], run.audio_sec)

    # ------------------------------------------------------------------ M1: transcription

    def transcription(self, f: MetricFilter) -> dict[str, Any]:
        rows = []
        total_proc = total_audio = 0.0
        for run, title in self.transcription_runs(f):
            if not run.audio_sec or run.duration_ms is None:
                continue
            proc = run.duration_ms / 1000.0
            rows.append({"lecture_id": run.lecture_id, "title": title, "started_at": run.started_at,
                         "audio_sec": round(run.audio_sec, 1), "processing_sec": round(proc, 2),
                         "rtf": round(proc / run.audio_sec, 4)})
            total_proc += proc
            total_audio += run.audio_sec
        rtfs = [r["rtf"] for r in rows]
        return {
            "runs": rows,
            "n": len(rows),
            "total_audio_sec": round(total_audio, 1),
            "total_processing_sec": round(total_proc, 2),
            "rtf_overall": round(total_proc / total_audio, 4) if total_audio else None,  # pooled
            "rtf_median": _r(percentile(rtfs, 50), 4),
        }

    # ------------------------------------------------------------------ M2/M3 (+ every task)

    def latency_by_task(self, f: MetricFilter) -> list[dict[str, Any]]:
        """Per task (and provider/model): latency of SUCCESSFUL requests (status ok)."""
        groups: dict[tuple[str, str, str], list[float | None]] = defaultdict(list)
        for c in self.calls(f):
            if c.status == OK:
                groups[(c.task, c.provider, c.model)].append(c.latency_ms)
        return [{"task": t, "provider": p, "model": m, **latency_stats(v)}
                for (t, p, m), v in sorted(groups.items())]

    # ------------------------------------------------------------------ M4

    def qa_latency(self, f: MetricFilter) -> list[dict[str, Any]]:
        """End-to-end /ask and /chat time per generator (successful questions only), split
        into answered vs refused, plus the retrieval part."""
        groups: dict[str, list[QALog]] = defaultdict(list)
        for row in self.qa_rows(f):
            if row.status == OK:
                groups[row.generator].append(row)
        out = []
        for gen, rows in sorted(groups.items()):
            answered = [r.latency_ms for r in rows if r.answerable]
            out.append({
                "generator": gen,
                **latency_stats(r.latency_ms for r in rows),
                "answered": latency_stats(answered),
                "refused_by_model": latency_stats(r.latency_ms for r in rows if r.refusal_reason == "not_in_chunks"),
                "refused_by_threshold": latency_stats(r.latency_ms for r in rows
                                                      if r.refusal_reason == "below_threshold"),
                "retrieval": latency_stats(r.retrieval_ms for r in rows),
            })
        return out

    # ------------------------------------------------------------------ M5

    def usage(self, f: MetricFilter, group: str) -> list[dict[str, Any]]:
        """Tokens, actual cost and equivalent cost grouped by task | lecture | day."""
        if group not in ("task", "lecture", "day"):
            raise ValueError(group)
        titles = dict(self.db.execute(select(Lecture.id, Lecture.title)).all())

        def key(c_task: str, lecture_id: uuid.UUID | None, ts: datetime) -> str:
            if group == "task":
                return c_task
            if group == "lecture":
                return str(lecture_id) if lecture_id else "none"
            return (ts.astimezone(UTC) if ts.tzinfo else ts).date().isoformat()

        acc: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": [], "equivalent": []})
        for c in self.calls(f):
            a = acc[key(c.task, c.lecture_id, c.ts)]
            a["calls"] += 1
            a["input_tokens"] += c.input_tokens or 0
            a["output_tokens"] += c.output_tokens or 0
            a["cost"].append(c.cost_usd)
            if c.task != ASR_TASK:
                a["equivalent"].append(self._equivalent(c))
        if self._asr_in_scope(f):
            for run, _title in self.transcription_runs(f):
                acc[key(ASR_TASK, run.lecture_id, run.started_at)]["equivalent"].append(self._asr_equivalent(run))

        out = []
        for k, a in sorted(acc.items()):
            cost, cost_unknown = _sum_or_none(a["cost"])
            eq, eq_unknown = _sum_or_none(a["equivalent"])
            row = {"key": k, "calls": a["calls"], "input_tokens": a["input_tokens"],
                   "output_tokens": a["output_tokens"], "total_tokens": a["input_tokens"] + a["output_tokens"],
                   "cost_usd": cost, "cost_unknown_calls": cost_unknown,
                   "equivalent_cost_usd": eq, "unpriced_calls": eq_unknown}
            if group == "lecture":
                row["label"] = titles.get(uuid.UUID(k), "(deleted lecture)") if k != "none" else "(no lecture)"
            else:
                row["label"] = k
            out.append(row)
        return out

    # ------------------------------------------------------------------ errors

    def errors(self, f: MetricFilter, recent: int = 20) -> dict[str, Any]:
        """Per task: failed requests (error / unavailable / rate_limited / not_configured) and
        JSON parse failures. A json_invalid row triggers one repair request; if the repair also
        fails it is logged with "(after repair)" and the user got 502 LLM_OUTPUT_INVALID."""
        per: dict[str, dict[str, int]] = defaultdict(lambda: {"requests": 0, "failed": 0, "json_invalid": 0,
                                                              "repair_failed": 0, "rate_limited": 0})
        failures: list[LLMCall] = []
        for c in self.calls(f):
            p = per[c.task]
            p["requests"] += 1
            if c.status in FAILED:
                p["failed"] += 1
                failures.append(c)
            if c.status == "rate_limited":
                p["rate_limited"] += 1
            if c.status == JSON_INVALID:
                p["json_invalid"] += 1
                failures.append(c)
                if c.error_message and "after repair" in c.error_message:
                    p["repair_failed"] += 1
        by_task = [{"task": t, **p, "error_rate": _rate(p["failed"], p["requests"]),
                    "parse_failure_rate": _rate(p["json_invalid"], p["requests"])}
                   for t, p in sorted(per.items())]
        total = sum(p["requests"] for p in per.values())
        failed = sum(p["failed"] for p in per.values())
        failures.sort(key=lambda c: c.ts, reverse=True)
        return {
            "requests": total,
            "failed": failed,
            "error_rate": _rate(failed, total),
            "json_invalid": sum(p["json_invalid"] for p in per.values()),
            "by_task": by_task,
            "recent": [{"ts": c.ts, "task": c.task, "provider": c.provider, "model": c.model, "status": c.status,
                        "error_type": c.error_type, "error_message": (c.error_message or "")[:300] or None,
                        "prompt_version": c.prompt_version, "attempt": c.attempt}
                       for c in failures[:recent]],
        }

    # ------------------------------------------------------------------ refusals

    def refusals(self, f: MetricFilter) -> list[dict[str, Any]]:
        """Per generator: answered vs refused by the threshold (no LLM call) vs by the model."""
        per: dict[str, dict[str, int]] = defaultdict(lambda: {"questions": 0, "answered": 0, "below_threshold": 0,
                                                              "not_in_chunks": 0, "errors": 0})
        for r in self.qa_rows(f):
            p = per[r.generator]
            p["questions"] += 1
            if r.status != OK:
                p["errors"] += 1
            elif r.answerable:
                p["answered"] += 1
            elif r.refusal_reason in REFUSAL_REASONS:
                p[r.refusal_reason] += 1
        out = []
        for gen, p in sorted(per.items()):
            ok = p["questions"] - p["errors"]
            refused = p["below_threshold"] + p["not_in_chunks"]
            out.append({"generator": gen, **p, "refused": refused, "refusal_rate": _rate(refused, ok),
                        "threshold_share_of_refusals": _rate(p["below_threshold"], refused)})
        return out

    # ------------------------------------------------------------------ prompt versions

    def prompts(self, f: MetricFilter) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str], list[LLMCall]] = defaultdict(list)
        for c in self.calls(f):
            if c.prompt_version:
                groups[(c.prompt_version, c.task)].append(c)
        out = []
        for (pv, task), rows in sorted(groups.items()):
            ok = [c for c in rows if c.status == OK]
            out.append({
                "prompt_version": pv, "prompt_id": rows[0].prompt_id, "task": task, "requests": len(rows),
                **{k: v for k, v in latency_stats(c.latency_ms for c in ok).items()},
                "error_rate": _rate(sum(c.status in FAILED for c in rows), len(rows)),
                "parse_failure_rate": _rate(sum(c.status == JSON_INVALID for c in rows), len(rows)),
                "mean_input_tokens": _r(sum(c.input_tokens or 0 for c in ok) / len(ok)) if ok else None,
                "mean_output_tokens": _r(sum(c.output_tokens or 0 for c in ok) / len(ok)) if ok else None,
            })
        return out

    # ------------------------------------------------------------------ KPI cards

    def summary(self, f: MetricFilter) -> dict[str, Any]:
        calls = self.calls(f)
        tokens_in = sum(c.input_tokens or 0 for c in calls)
        tokens_out = sum(c.output_tokens or 0 for c in calls)
        cost, cost_unknown = _sum_or_none(c.cost_usd for c in calls)
        eq_values = [self._equivalent(c) for c in calls if c.task != ASR_TASK]
        if self._asr_in_scope(f):
            eq_values += [self._asr_equivalent(run) for run, _t in self.transcription_runs(f)]
        eq, unpriced = _sum_or_none(eq_values)
        failed = sum(c.status in FAILED for c in calls)
        json_invalid = sum(c.status == JSON_INVALID for c in calls)
        qa = [r for r in self.qa_rows(f) if r.status == OK]
        tr = self.transcription(f)
        first = min((c.ts for c in calls), default=None)
        last = max((c.ts for c in calls), default=None)
        return {
            "filters": f.as_dict(),
            "calls": len(calls),
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
            "cost_usd": cost,
            "cost_unknown_calls": cost_unknown,
            "equivalent_cost_usd": eq,
            "unpriced_calls": unpriced,
            "failed_calls": failed,
            "error_rate": _rate(failed, len(calls)),
            "json_invalid_calls": json_invalid,
            "parse_failure_rate": _rate(json_invalid, len(calls)),
            "rtf_overall": tr["rtf_overall"],
            "transcriptions": tr["n"],
            "questions": len(qa),
            "qa_latency": latency_stats(r.latency_ms for r in qa),
            "first_call_at": first,
            "last_call_at": last,
            "pricing_checked": self.pricing.checked,
        }

    # ------------------------------------------------------------------ filter options

    def filter_options(self) -> dict[str, Any]:
        tasks = sorted({t for (t,) in self.db.execute(select(LLMCall.task).distinct()).all()})
        qa_gens = {g for (g,) in self.db.execute(select(QALog.generator).distinct()).all()}
        first = self.db.scalar(select(LLMCall.ts).order_by(LLMCall.ts).limit(1))
        last = self.db.scalar(select(LLMCall.ts).order_by(LLMCall.ts.desc()).limit(1))
        return {
            "tasks": [t for t in tasks if not t.startswith(EVAL_TASK_PREFIX)],
            "eval_tasks": [t for t in tasks if t.startswith(EVAL_TASK_PREFIX)],
            "generators": self.generators.names(),
            "generators_with_questions": sorted(qa_gens & set(self.generators.names())),
            "first_call_at": first,
            "last_call_at": last,
        }
