"""Phase 11 metrics (services/llmops.py + /api/llmops/*) on hand-seeded log rows."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.errors import AppError
from app.models.chat import QALog
from app.models.lecture import Lecture
from app.models.llmops import LLMCall, PipelineRun
from app.models.user import User
from app.services.llm.pricing import load_pricing
from app.services.llmops import LlmOpsMetrics, MetricFilter, latency_stats, percentile

D1 = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
D2 = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)


def _call(task, latency, *, ts=D1, provider="groq", model="openai/gpt-oss-120b", status="ok", inp=1000, out=500,
          lecture_id=None, prompt=None, err=None, cost=0.0):
    return LLMCall(ts=ts, task=task, provider=provider, model=model, model_version=model, latency_ms=latency,
                   status=status, input_tokens=inp if status in ("ok", "json_invalid") else None,
                   output_tokens=out if status in ("ok", "json_invalid") else None, lecture_id=lecture_id,
                   prompt_id=prompt.split("@")[0] if prompt else None, prompt_version=prompt, cost_usd=cost,
                   error_message=err, attempt=1)


@pytest.fixture
def seeded(db):
    user = User(email="m@example.com", password_hash="x")
    db.add(user)
    db.flush()
    lec = Lecture(user_id=user.id, title="Serverless", status="ready", progress=100, duration_sec=300.0)
    db.add(lec)
    db.flush()
    db.add_all([
        _call("summary", 1000, lecture_id=lec.id, prompt="summary@v1"),
        _call("summary", 3000, lecture_id=lec.id, prompt="summary@v1"),
        _call("quiz", 2000, ts=D2, lecture_id=lec.id, prompt="quiz@v1"),
        _call("quiz", 500, ts=D2, status="json_invalid", inp=10, out=10, prompt="quiz@v1",
              err="output failed schema validation"),
        _call("quiz", 400, ts=D2, status="json_invalid", inp=20, out=20, prompt="quiz@v1",
              err="output failed schema validation (after repair)"),
        _call("rag_answer", 700, ts=D2, prompt="rag_answer@v1"),
        _call("rag_answer", 9000, ts=D2, provider="ollama", model="study-buddy-qwen", prompt="rag_answer@v1"),
        _call("rag_answer", 4000, ts=D2, provider="ollama", model="study-buddy-qwen", status="unavailable",
              prompt="rag_answer@v1", cost=None),
        _call("rag_query", 30, provider="local", model="BAAI/bge-small-en-v1.5", inp=None, out=None),
        _call("asr", 1200, provider="groq", model="whisper-large-v3-turbo", inp=None, out=None, lecture_id=lec.id),
        _call("grading", 800, model="llama-not-priced"),
        _call("eval_rag_answer", 600, ts=D2, prompt="rag_answer@v1"),  # eval traffic: excluded by default
    ])
    db.add(PipelineRun(lecture_id=lec.id, stage="transcribing", started_at=D1, ended_at=D1 + timedelta(seconds=30),
                       duration_ms=30000.0, audio_sec=300.0, status="ok"))
    db.add(PipelineRun(lecture_id=lec.id, stage="extracting_audio", started_at=D1, duration_ms=1000.0,
                       audio_sec=300.0, status="ok"))
    db.add_all([
        QALog(lecture_id=lec.id, endpoint="ask", generator="cloud", question="q", min_score=0.5, status="ok",
              answerable=True, latency_ms=800.0, retrieval_ms=40.0, created_at=D2),
        QALog(lecture_id=lec.id, endpoint="ask", generator="cloud", question="q", min_score=0.5, status="ok",
              answerable=False, refusal_reason="below_threshold", latency_ms=50.0, retrieval_ms=40.0, created_at=D2),
        QALog(lecture_id=lec.id, endpoint="ask", generator="cloud", question="q", min_score=0.5, status="ok",
              answerable=False, refusal_reason="not_in_chunks", latency_ms=600.0, retrieval_ms=40.0, created_at=D2),
        QALog(lecture_id=lec.id, endpoint="ask", generator="finetuned", question="q", min_score=0.5,
              status="error", error_code="MODEL_UNAVAILABLE", created_at=D2),
    ])
    db.commit()
    return lec


@pytest.fixture
def metrics(db, generator_registry):
    return LlmOpsMetrics(db, load_pricing(), generator_registry)


def test_percentile_linear_interpolation():
    assert percentile([], 50) is None
    assert percentile([5], 95) == 5
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([0, 10], 95) == pytest.approx(9.5)
    assert latency_stats([None, 100, 300]) == {"n": 2, "p50_ms": 200.0, "p95_ms": 290.0, "mean_ms": 200.0}


def test_latency_by_task_uses_only_successful_calls(seeded, metrics):
    rows = {(r["task"], r["provider"]): r for r in metrics.latency_by_task(MetricFilter())}
    assert rows[("summary", "groq")]["n"] == 2 and rows[("summary", "groq")]["p50_ms"] == 2000.0
    assert rows[("quiz", "groq")]["n"] == 1  # the two json_invalid rows are not latency samples
    assert rows[("rag_answer", "ollama")]["n"] == 1
    assert ("eval_rag_answer", "groq") not in rows
    assert ("eval_rag_answer", "groq") in {(r["task"], r["provider"]) for r in
                                           metrics.latency_by_task(MetricFilter(include_eval=True))}


def test_summary_tokens_costs_errors_and_rtf(seeded, metrics):
    s = metrics.summary(MetricFilter())
    assert s["calls"] == 11  # eval row excluded
    assert s["failed_calls"] == 1 and s["error_rate"] == round(1 / 11, 4)
    assert s["json_invalid_calls"] == 2
    assert s["cost_usd"] == 0.0 and s["cost_unknown_calls"] == 1  # free tier; the failed ollama row had None
    # equivalent: gpt-oss-120b ok rows at $0.15 / $0.60 per 1M: summary x2, quiz x1, rag_answer x1 (1000 in, 500 out)
    # + the two json_invalid quiz rows (10/10 and 20/20 tokens; they were really sent and billed);
    # llama grading -> unpriced; local/ollama -> 0; asr: 300 s at the $0.000667/min reference price
    per = (1000 * 0.15 + 500 * 0.60) / 1e6
    expected = 4 * per + (30 * 0.15 + 30 * 0.60) / 1e6 + 300 / 60 * 0.000667
    assert s["equivalent_cost_usd"] == pytest.approx(expected, abs=1e-8)
    assert s["unpriced_calls"] == 1
    assert s["rtf_overall"] == 0.1  # 30 s processing / 300 s audio
    assert s["questions"] == 3 and s["qa_latency"]["n"] == 3


def test_usage_grouped_by_task_lecture_day(seeded, metrics):
    by_task = {r["key"]: r for r in metrics.usage(MetricFilter(), "task")}
    assert by_task["summary"]["total_tokens"] == 3000
    assert by_task["asr"]["equivalent_cost_usd"] == pytest.approx(300 / 60 * 0.000667)
    by_lecture = {r["label"]: r for r in metrics.usage(MetricFilter(), "lecture")}
    assert "Serverless" in by_lecture and "(no lecture)" in by_lecture
    by_day = {r["key"] for r in metrics.usage(MetricFilter(), "day")}
    assert by_day == {"2026-11-07", "2026-11-08"}
    with pytest.raises(ValueError):
        metrics.usage(MetricFilter(), "month")


def test_date_task_and_generator_filters(seeded, metrics):
    assert metrics.summary(MetricFilter(date_from=date(2026, 11, 8)))["calls"] == 6
    assert metrics.summary(MetricFilter(date_to=date(2026, 11, 7)))["calls"] == 5
    assert metrics.summary(MetricFilter(task="quiz"))["calls"] == 3
    assert metrics.summary(MetricFilter(task="eval_rag_answer"))["calls"] == 1  # explicit task wins
    ft = metrics.summary(MetricFilter(generator="finetuned"))
    assert ft["calls"] == 2 and ft["failed_calls"] == 1
    assert ft["rtf_overall"] == 0.1  # transcription is not generator-specific
    with pytest.raises(AppError) as exc:
        metrics.summary(MetricFilter(generator="gpt-9"))
    assert exc.value.code == "UNKNOWN_GENERATOR"


def test_errors_and_parse_failures_per_task(seeded, metrics):
    e = metrics.errors(MetricFilter())
    quiz = next(r for r in e["by_task"] if r["task"] == "quiz")
    assert (quiz["requests"], quiz["json_invalid"], quiz["repair_failed"]) == (3, 2, 1)
    assert quiz["parse_failure_rate"] == round(2 / 3, 4)
    rag = next(r for r in e["by_task"] if r["task"] == "rag_answer")
    assert rag["failed"] == 1 and rag["error_rate"] == round(1 / 3, 4)
    assert {r["status"] for r in e["recent"]} == {"json_invalid", "unavailable"}


def test_refusals_split_by_layer(seeded, metrics):
    rows = {r["generator"]: r for r in metrics.refusals(MetricFilter())}
    c = rows["cloud"]
    assert (c["answered"], c["below_threshold"], c["not_in_chunks"], c["refused"]) == (1, 1, 1, 2)
    assert c["refusal_rate"] == round(2 / 3, 4) and c["threshold_share_of_refusals"] == 0.5
    assert rows["finetuned"]["errors"] == 1 and rows["finetuned"]["refusal_rate"] is None


def test_qa_latency_per_generator(seeded, metrics):
    [cloud] = metrics.qa_latency(MetricFilter())  # finetuned only has an error row
    assert cloud["generator"] == "cloud" and cloud["n"] == 3
    assert cloud["answered"]["n"] == 1 and cloud["refused_by_threshold"]["p50_ms"] == 50.0
    assert cloud["retrieval"]["p50_ms"] == 40.0


def test_prompt_version_metrics(seeded, metrics):
    rows = {(r["prompt_version"], r["task"]): r for r in metrics.prompts(MetricFilter())}
    assert rows[("quiz@v1", "quiz")]["requests"] == 3
    assert rows[("quiz@v1", "quiz")]["parse_failure_rate"] == round(2 / 3, 4)
    assert rows[("summary@v1", "summary")]["p50_ms"] == 2000.0
    assert rows[("rag_answer@v1", "rag_answer")]["error_rate"] == round(1 / 3, 4)


def test_transcription_rtf_per_lecture(seeded, metrics):
    t = metrics.transcription(MetricFilter())
    assert t["n"] == 1 and t["runs"][0]["rtf"] == 0.1 and t["runs"][0]["title"] == "Serverless"


# ---------------------------------------------------------------------------- API


def test_llmops_endpoints(client, auth_headers, seeded):
    for path in ("/summary", "/latency", "/qa-latency", "/usage?group=day", "/transcription", "/errors",
                 "/refusals", "/prompts", "/filters", "/eval/runs", "/eval/compare"):
        r = client.get(f"/api/llmops{path}", headers=auth_headers)
        assert r.status_code == 200, (path, r.text)
    s = client.get("/api/llmops/summary?date_from=2026-11-08&task=quiz", headers=auth_headers).json()
    assert s["calls"] == 3 and s["filters"]["task"] == "quiz"
    opts = client.get("/api/llmops/filters", headers=auth_headers).json()
    assert "summary" in opts["tasks"] and opts["eval_tasks"] == ["eval_rag_answer"]


def test_llmops_errors(client, auth_headers):
    assert client.get("/api/llmops/summary").status_code == 401
    r = client.get("/api/llmops/summary?date_from=2026-11-09&date_to=2026-11-01", headers=auth_headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = client.get("/api/llmops/summary?generator=gpt-9", headers=auth_headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_GENERATOR"
    assert client.get("/api/llmops/usage?group=month", headers=auth_headers).status_code == 422
    r = client.get(f"/api/llmops/eval/runs/{uuid.uuid4()}", headers=auth_headers)
    assert r.status_code == 404 and r.json()["error"]["code"] == "EVAL_RUN_NOT_FOUND"
