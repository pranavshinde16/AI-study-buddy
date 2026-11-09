"""The evaluation harness behind `python -m eval.run` (IMPLEMENTATION_PLAN §7.2–7.3, Phase 11).

For one golden set on one lecture it writes:

1. ONE "retrieval" run (the retriever is shared by every generator, so M6 is reported once):
   every question is embedded exactly as /ask does (bge prefix, top-k), and each answerable
   question is scored against its gold time range: Hit@k, MRR, context precision. The same
   scores give the RAG_MIN_SCORE report (score distribution of on/near/off-topic questions).
2. ONE run per generator (cloud | finetuned | base | ...): every question goes through the real
   RagService.answer path (threshold, prompt, citation check). Then, per question:
     - refusal decision vs the label, split by layer (threshold vs model)         -> M8
     - if answered: the judge splits the answer into claims and checks each one
       against the chunks the model saw                                          -> M7
     - if answerable and answered: the judge compares it with reference_answer    -> correctness
     - end-to-end latency
Rows go to eval_runs / eval_items as they are produced, so an interrupted run keeps its items.
All model calls are logged in llm_calls under eval_* tasks (kept out of the live metrics).
"""

import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.models.lecture import Lecture
from app.models.llmops import EvalItem, EvalRun
from app.services.embeddings import model_version_of
from app.services.evaluation.golden import GoldenItem
from app.services.evaluation.judge import Judge
from app.services.evaluation.metrics import (
    Span,
    aggregate_generation,
    aggregate_retrieval,
    retrieval_item_metrics,
    threshold_report,
)
from app.services.indexing import LectureIndexer
from app.services.lectures import TRANSCRIPT_READY
from app.services.rag import RagAnswer, RagService

TASK_PREFIX = "eval_"
FATAL_CODES = frozenset({"MODEL_UNAVAILABLE", "PROVIDER_NOT_CONFIGURED", "UNKNOWN_GENERATOR"})

Progress = Callable[[str], None]


class EvalSetupError(Exception):
    pass


@dataclass
class HarnessResult:
    retrieval_run_id: uuid.UUID | None = None
    generator_runs: dict[str, uuid.UUID] = field(default_factory=dict)
    summaries: dict[str, dict[str, Any]] = field(default_factory=dict)


def ks_for(top_k: int) -> list[int]:
    return sorted({k for k in (1, 3, top_k) if k <= top_k})


class EvalHarness:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session] | Callable[[], Session],
                 rag: RagService, indexer: LectureIndexer, judge: Judge | None,
                 progress: Progress = print) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.rag = rag
        self.indexer = indexer
        self.judge = judge  # None = --no-judge (refusals, retrieval and latency only)
        self.progress = progress

    # ------------------------------------------------------------------ entry point

    def run(self, *, golden_set: str, items: Sequence[GoldenItem], lecture_id: uuid.UUID,
            generators: Sequence[str], retrieval: bool = True) -> HarnessResult:
        with self.session_factory() as db:
            lecture = db.get(Lecture, lecture_id)
            if lecture is None:
                raise EvalSetupError(f"Lecture {lecture_id} not found")
            if lecture.status not in TRANSCRIPT_READY:
                raise EvalSetupError(f"Lecture {lecture_id} has no transcript yet (status {lecture.status})")
            for g in generators:
                self.rag.generators.get(g)  # unknown name -> error before any work
            idx = self.indexer.ensure_indexed(db, lecture.id, lecture.user_id)
            self.progress(f"Lecture '{lecture.title}' ({lecture.duration_sec or 0:.0f} s): {idx.chunks} chunks"
                          + (" (indexed now)" if idx.indexed_now else ""))
            title, owner = lecture.title, lecture.user_id

        result = HarnessResult()
        if retrieval:
            result.retrieval_run_id, result.summaries["retrieval"] = self._retrieval(golden_set, items, lecture_id)
        for g in generators:
            run_id, summary = self._generation(golden_set, items, lecture_id, title, owner, g)
            result.generator_runs[g] = run_id
            result.summaries[g] = summary
        return result

    # ------------------------------------------------------------------ helpers

    def _config(self) -> dict[str, Any]:
        s = self.settings
        return {"top_k": s.rag_top_k, "rag_min_score": s.rag_min_score, "embedding_model": s.embedding_model,
                "chunk_target_words": s.chunk_target_words, "chunk_max_sec": s.chunk_max_sec,
                "chunk_overlap": s.chunk_overlap, "ks": ks_for(s.rag_top_k)}

    @staticmethod
    def _finish(db: Session, run: EvalRun, metrics: dict[str, Any], status: str, error: str | None = None) -> None:
        run.metrics_json = metrics
        run.status = status
        run.error = error
        run.finished_at = datetime.now(UTC)
        db.commit()

    # ------------------------------------------------------------------ 1. retrieval (M6) + threshold

    def _retrieval(self, golden_set: str, items: Sequence[GoldenItem],
                   lecture_id: uuid.UUID) -> tuple[uuid.UUID, dict[str, Any]]:
        ks = ks_for(self.settings.rag_top_k)
        embedder_version = model_version_of(self.rag.embeddings.embedder)
        with self.session_factory() as db:
            run = EvalRun(golden_set=golden_set, generator="retrieval", model=embedder_version, source="harness",
                          lecture_id=lecture_id, n_items=len(items), config_json=self._config(), status="running")
            db.add(run)
            db.commit()
            per_item, rows = [], []
            try:
                for n, it in enumerate(items, start=1):
                    t0 = time.perf_counter()
                    hits = self.rag.retrieve(lecture_id, it.question, task=f"{TASK_PREFIX}rag_query")
                    ms = round((time.perf_counter() - t0) * 1000, 1)
                    chunks = [{"label": f"C{i + 1}", "chunk_idx": int(h.metadata.get("idx", -1)),
                               "start": float(h.metadata["start"]), "end": float(h.metadata["end"]),
                               "score": round(h.score, 4)} for i, h in enumerate(hits)]
                    top = chunks[0]["score"] if chunks else None
                    m: dict[str, Any] = {}
                    if it.answerable and it.gold_start is not None and it.gold_end is not None:
                        m = retrieval_item_metrics([Span(c["start"], c["end"]) for c in chunks],
                                                   Span(it.gold_start, it.gold_end), ks)
                        per_item.append(m)
                    rows.append({"id": it.id, "kind": it.kind, "answerable": it.answerable, "top_score": top})
                    db.add(EvalItem(run_id=run.id, lecture_id=lecture_id, item_key=it.id, kind=it.kind,
                                    question=it.question, answerable=it.answerable, gold_start=it.gold_start,
                                    gold_end=it.gold_end, reference_answer=it.reference_answer,
                                    retrieved_json=chunks, top_score=top, latency_ms=ms, metrics_json=m or None))
                    db.commit()
                    hit = "" if not m else f" first relevant rank {m['first_relevant_rank'] or '-'}"
                    self.progress(f"[retrieval] {n}/{len(items)} {it.id} ({it.kind}): top {top}{hit}")
                summary = {"retrieval": aggregate_retrieval(per_item, ks),
                           "threshold": threshold_report(rows, self.settings.rag_min_score)}
                self._finish(db, run, summary, "ok")
            except Exception as exc:
                db.rollback()
                self._finish(db, run, {}, "failed", f"{type(exc).__name__}: {exc}"[:2000])
                raise
            return run.id, summary

    # ------------------------------------------------------------------ 2. one generator

    def _generation(self, golden_set: str, items: Sequence[GoldenItem], lecture_id: uuid.UUID, title: str,
                    owner: uuid.UUID | None, generator: str) -> tuple[uuid.UUID, dict[str, Any]]:
        gen = self.rag.generators.get(generator)
        prompts = self.rag.generators.get(generator).llm.prompts
        prompt_versions = {"rag_answer": prompts.get("rag_answer").tag}
        if self.judge is not None:
            prompt_versions |= {"eval_faithfulness": prompts.get("eval_faithfulness").tag,
                                "eval_correctness": prompts.get("eval_correctness").tag,
                                "judge": f"{self.judge.provider}/{self.judge.model}"}
        config = self._config() | {"generator": generator, "provider": gen.provider, "judge_enabled": self.judge is not None}
        if self.judge is not None:
            self.judge.stats.calls = self.judge.stats.tokens = 0
            self.judge.stats.errors = []
        with self.session_factory() as db:
            run = EvalRun(golden_set=golden_set, generator=generator, model=gen.model, source="harness",
                          lecture_id=lecture_id, n_items=len(items), config_json=config,
                          prompt_versions=prompt_versions, status="running")
            db.add(run)
            db.commit()
            ok_items: list[dict[str, Any]] = []
            errors: dict[str, int] = {}
            seen_versions: set[str] = set()
            fatal: str | None = None
            try:
                for n, it in enumerate(items, start=1):
                    row, item_metrics = self._one(lecture_id, title, generator, it)
                    row.run_id = run.id
                    db.add(row)
                    db.commit()
                    if row.status == "ok":
                        ok_items.append(item_metrics)
                        if item_metrics.get("model_version"):
                            seen_versions.add(item_metrics["model_version"])
                    else:
                        code = item_metrics.get("error_code", "ERROR")
                        errors[code] = errors.get(code, 0) + 1
                        if code in FATAL_CODES and not ok_items:
                            fatal = f"{code}: {item_metrics.get('error')}"
                    self.progress(f"[{generator}] {n}/{len(items)} {it.id}: {self._describe(row, item_metrics)}")
                    if fatal:
                        self.progress(f"[{generator}] stopping: {fatal}")
                        break
                summary = aggregate_generation(ok_items) | {
                    "errors": errors, "items_attempted": len(ok_items) + sum(errors.values()),
                    "model_versions": sorted(seen_versions),
                    "judge": None if self.judge is None else {
                        "calls": self.judge.stats.calls, "tokens": self.judge.stats.tokens,
                        "errors": len(self.judge.stats.errors)},
                }
                status = "failed" if fatal else ("partial" if errors else "ok")
                if seen_versions:
                    run.model = sorted(seen_versions)[-1]
                self._finish(db, run, summary, status, fatal)
            except Exception as exc:  # interrupted (Ctrl+C) or unexpected: keep what we have
                db.rollback()
                self._finish(db, run, aggregate_generation(ok_items) if ok_items else {}, "failed",
                             f"{type(exc).__name__}: {exc}"[:2000])
                raise
            return run.id, summary

    @staticmethod
    def _describe(row: EvalItem, m: dict[str, Any]) -> str:
        if row.status != "ok":
            return f"ERROR {m.get('error_code')}"
        what = "answered" if row.predicted_answerable else f"refused ({row.refusal_reason})"
        extra = []
        if m.get("faithfulness") is not None:
            extra.append(f"faithfulness {m['faithfulness']}")
        if m.get("correctness") is not None:
            extra.append(f"correctness {m['correctness']}")
        if m.get("judge_error"):
            extra.append(f"judge error {m['judge_error']}")
        ok = "ok" if m.get("decision_correct") else "WRONG"
        return f"{what} [{ok}] {row.latency_ms:.0f} ms" + (" · " + ", ".join(extra) if extra else "")

    def _one(self, lecture_id: uuid.UUID, title: str, generator: str,
             it: GoldenItem) -> tuple[EvalItem, dict[str, Any]]:
        row = EvalItem(lecture_id=lecture_id, item_key=it.id, kind=it.kind, question=it.question,
                       answerable=it.answerable, gold_start=it.gold_start, gold_end=it.gold_end,
                       reference_answer=it.reference_answer)
        base = {"answerable": it.answerable, "kind": it.kind}
        try:
            res: RagAnswer = self.rag.answer(lecture_id=lecture_id, user_id=None, title=title, question=it.question,
                                             generator=generator, task_prefix=TASK_PREFIX)
        except AppError as exc:
            row.status = "error"
            m = base | {"error_code": exc.code, "error": exc.message[:500]}
            row.metrics_json = m
            return row, m

        row.status = "ok"
        row.predicted_answer = res.answer
        row.predicted_answerable = res.answerable
        row.refusal_reason = res.refusal_reason
        row.top_score = res.top_score
        row.latency_ms = res.latency_ms
        row.retrieved_json = [{"label": c.label, "chunk_idx": c.chunk_idx, "start": c.start, "end": c.end,
                               "score": c.score, "cited": any(s.chunk_id == c.label and s.cited for s in res.sources)}
                              for c in res.retrieved]
        m: dict[str, Any] = base | {
            "predicted_answerable": res.answerable, "refusal_reason": res.refusal_reason,
            "latency_ms": res.latency_ms, "retrieval_ms": res.retrieval_ms, "llm_calls": res.llm_calls,
            "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
            "citation_check": res.citation_check, "model_version": res.model,
            "decision_correct": it.answerable == res.answerable,
            "faithfulness": None, "claims_total": None, "correctness": None,
        }
        if res.answerable and self.judge is not None:
            try:
                f = self.judge.faithfulness(question=it.question, answer=res.answer,
                                            chunks=[(c.label, c.text) for c in res.retrieved])
                m |= {"faithfulness": f.faithfulness, "claims_total": f.total, "claims_supported": f.supported,
                      "claims": f.claims, "judge_model_version": f.model_version}
                if it.answerable and it.reference_answer:
                    c = self.judge.correctness(question=it.question, answer=res.answer, reference=it.reference_answer)
                    m |= {"correctness": c.score, "correctness_reason": c.reason}
            except AppError as exc:
                self.judge.stats.errors.append(exc.code)
                m["judge_error"] = exc.code
        row.metrics_json = m
        return row, m
