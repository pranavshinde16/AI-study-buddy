"""Phase 11 evaluation: golden-set parsing, metric maths, the harness (fake LLM + judge, real
in-memory Chroma), offline import of the Phase 10 files, and the eval API."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.models.llmops import EvalItem, EvalRun, LLMCall
from app.services.evaluation.golden import GoldenSetError, load_golden, parse_golden
from app.services.evaluation.harness import EvalHarness, EvalSetupError, ks_for
from app.services.evaluation.judge import Judge
from app.services.evaluation.metrics import (
    Span,
    aggregate_generation,
    aggregate_retrieval,
    overlaps,
    retrieval_item_metrics,
    threshold_report,
)
from app.services.evaluation.offline import import_all, import_file
from app.services.llm.providers import ProviderError


def _line(**kw):
    base = {"id": "q1", "question": "How do cells make energy?", "answerable": True, "gold_start": 0.0,
            "gold_end": 19.5, "reference_answer": "From food.", "kind": "on_topic"}
    return json.dumps(base | kw)


# ---------------------------------------------------------------------------- golden sets


def test_golden_parse_valid_and_warnings():
    text = "\n".join([_line(), "", _line(id="q2", answerable=False, gold_start=None, gold_end=None,
                                         reference_answer=None, kind="off_topic", extra=1)])
    items, problems, warnings = parse_golden(text)
    assert [i.id for i in items] == ["q1", "q2"] and problems == []
    assert any("unknown fields" in w for w in warnings)


@pytest.mark.parametrize("line, fragment", [
    ("{not json", "not valid JSON"),
    (_line(gold_start=None, gold_end=None), "need gold_start"),
    (_line(gold_start=30, gold_end=10), "before gold_start"),
    (_line(reference_answer=""), "reference_answer"),
    (_line(kind="sideways"), "kind"),
    (_line(answerable=False, gold_start=5.0, gold_end=None, reference_answer=None, kind="off_topic"), "both"),
])
def test_golden_parse_problems(line, fragment):
    _items, problems, _w = parse_golden(line)
    assert problems and fragment in problems[0]


def test_golden_duplicates_empty_and_duration():
    assert "duplicate id" in parse_golden(_line() + "\n" + _line())[1][0]
    assert parse_golden("")[1] == ["the file has no questions yet"]
    assert "after the lecture's end" in parse_golden(_line(gold_end=500.0), duration_sec=120.0)[1][0]


def test_load_golden_file_errors(tmp_path):
    with pytest.raises(GoldenSetError, match="not found"):
        load_golden("missing", directory=tmp_path)
    with pytest.raises(GoldenSetError):
        load_golden("../escape", directory=tmp_path)
    (tmp_path / "g.jsonl").write_text(_line(kind="bad"), encoding="utf-8")
    with pytest.raises(GoldenSetError) as exc:
        load_golden("g", directory=tmp_path)
    assert exc.value.problems


# ---------------------------------------------------------------------------- metric maths


def test_overlap_and_retrieval_item_metrics():
    assert overlaps(Span(0, 10), Span(10, 20)) and not overlaps(Span(0, 9.9), Span(10, 20))
    chunks = [Span(50, 60), Span(0, 12), Span(30, 40), Span(10, 20)]
    m = retrieval_item_metrics(chunks, Span(11, 15), ks=[1, 3, 4])
    assert m["relevant_ranks"] == [2, 4] and m["first_relevant_rank"] == 2
    assert (m["hit@1"], m["hit@3"], m["hit@4"]) == (0, 1, 1)
    assert m["reciprocal_rank"] == 0.5 and m["context_precision"] == 0.5
    assert m["average_precision"] == round((1 / 2 + 2 / 4) / 2, 4)
    none = retrieval_item_metrics(chunks, Span(100, 110), ks=[1, 3, 4])
    assert none["reciprocal_rank"] == 0.0 and none["first_relevant_rank"] is None
    agg = aggregate_retrieval([m, none], ks=[1, 3])
    assert agg["mrr"] == 0.25 and agg["hit@3"] == 0.5 and agg["n"] == 2
    assert ks_for(5) == [1, 3, 5] and ks_for(2) == [1, 2]


def test_threshold_report_describes_but_does_not_choose():
    rows = [{"id": "a", "kind": "on_topic", "answerable": True, "top_score": 0.7},
            {"id": "b", "kind": "on_topic", "answerable": True, "top_score": 0.48},
            {"id": "c", "kind": "near_topic", "answerable": False, "top_score": 0.55},
            {"id": "d", "kind": "off_topic", "answerable": False, "top_score": 0.3}]
    r = threshold_report(rows, 0.5)
    assert r["answerable"]["wrongly_refused_by_threshold"] == 1
    assert r["unanswerable"]["refused_by_threshold"] == 1 and r["unanswerable"]["passed_to_model"] == 1
    assert r["separable"] is False and r["gap"] == round(0.48 - 0.55, 4)
    assert r["by_kind"]["on_topic"]["below_ids"] == ["b"]
    assert "proposed" not in json.dumps(r)


def test_aggregate_generation_refusal_split_and_faithfulness():
    def it(ans, pred, reason=None, kind="on_topic", faith=None, corr=None, lat=100.0, claims=None):
        return {"answerable": ans, "kind": kind, "predicted_answerable": pred, "refusal_reason": reason,
                "latency_ms": lat, "faithfulness": faith, "claims_total": claims, "correctness": corr}
    items = [it(True, True, faith=1.0, corr=1.0, claims=2), it(True, True, faith=0.5, corr=0.5, claims=2),
             it(True, False, "below_threshold"),
             it(False, False, "below_threshold", "off_topic"), it(False, False, "not_in_chunks", "near_topic"),
             it(False, True, kind="near_topic", faith=1.0, claims=1)]
    a = aggregate_generation(items)
    assert a["refusal_accuracy"] == round(2 / 3, 4)
    assert a["refusal"]["unanswerable"]["by_threshold"] == 1 and a["refusal"]["unanswerable"]["by_model"] == 1
    assert a["refusal"]["by_kind"]["near_topic"]["rate"] == 0.5
    assert a["refusal"]["false_refusals"]["by_threshold"] == 1
    assert a["decision_accuracy"] == round(4 / 6, 4)
    assert a["faithfulness"] == round(2.5 / 3, 4) and a["hallucination_rate"] == round(1 / 3, 4)
    assert a["correctness_answered"] == 0.75 and a["correctness_all_answerable"] == 0.5
    assert a["answered_unanswerable"] == 1


# ---------------------------------------------------------------------------- harness


@pytest.fixture
def indexed_lecture(make_ready_lecture):
    return make_ready_lecture(n=12, summarize=False)


@pytest.fixture
def harness(settings, session_factory, rag, indexer, lecture_llm_client):
    lines = []
    return EvalHarness(settings, session_factory, rag, indexer, Judge(settings, lecture_llm_client),
                       progress=lines.append), lines


def _items():
    text = "\n".join([
        _line(id="a1", question="How do cells turn food into energy?", gold_start=0.0, gold_end=19.5),
        _line(id="a2", question="What does sentence 7 say about energy from food?", gold_start=70.0, gold_end=79.5),
        _line(id="n1", question="Who won the football world cup in Qatar?", answerable=False, gold_start=None,
              gold_end=None, reference_answer=None, kind="off_topic"),
    ])
    return parse_golden(text)[0]


def test_harness_writes_retrieval_and_generator_runs(harness, indexed_lecture, session_factory, fake_llm):
    h, lines = harness
    fake_llm.judge_supported = [True, False]
    fake_llm.judge_score = 0.5
    res = h.run(golden_set="g1", items=_items(), lecture_id=indexed_lecture, generators=["cloud"])
    with session_factory() as db:
        runs = {r.generator: r for r in db.scalars(select(EvalRun))}
        assert set(runs) == {"retrieval", "cloud"} and all(r.status == "ok" for r in runs.values())
        ret = runs["retrieval"].metrics_json
        assert ret["retrieval"]["n"] == 2 and 0 <= ret["retrieval"]["mrr"] <= 1
        assert ret["threshold"]["threshold"] == 0.35 and "off_topic" in ret["threshold"]["by_kind"]
        cloud = runs["cloud"].metrics_json
        assert cloud["n"] == 3
        # off-topic question: refused by the threshold (fake embedder shares no words with it)
        assert cloud["refusal"]["unanswerable"]["by_threshold"] == 1 and cloud["refusal_accuracy"] == 1.0
        assert cloud["faithfulness"] == 0.5 and cloud["hallucination_rate"] == 1.0
        assert cloud["correctness_answered"] == 0.5
        assert runs["cloud"].prompt_versions["eval_faithfulness"] == "eval_faithfulness@v1"
        assert runs["cloud"].prompt_versions["judge"] == "groq/qwen/qwen3.8-27b"
        items = db.scalars(select(EvalItem).where(EvalItem.run_id == runs["cloud"].id)).all()
        assert {i.item_key for i in items} == {"a1", "a2", "n1"}
        a1 = next(i for i in items if i.item_key == "a1")
        assert a1.predicted_answerable and a1.retrieved_json and a1.metrics_json["claims_total"] == 2
        tasks = {t for (t,) in db.execute(select(LLMCall.task).distinct())}
        assert {"eval_rag_query", "eval_rag_answer", "eval_judge_faithfulness", "eval_judge_correctness"} <= tasks
        assert "rag_answer" not in tasks  # eval traffic never lands in the live-traffic task names
        judge_models = {m for (m,) in db.execute(select(LLMCall.model).where(LLMCall.task.startswith("eval_judge")))}
        assert judge_models == {"qwen/qwen3.8-27b"}
    assert res.generator_runs["cloud"] == runs["cloud"].id
    assert any(line.startswith("[cloud] 3/3") for line in lines)


def test_judge_gets_no_reasoning_effort_and_never_falls_back(harness, indexed_lecture, llm_provider):
    h, _ = harness
    h.run(golden_set="g", items=_items()[:1], lecture_id=indexed_lecture, generators=["cloud"], retrieval=False)
    judge_calls = [c for c in llm_provider.calls if c["model"] == "qwen/qwen3.8-27b"]
    assert judge_calls and all(c["reasoning_effort"] is None for c in judge_calls)
    gen_calls = [c for c in llm_provider.calls if c["model"] == "openai/gpt-oss-120b"]
    assert gen_calls and all(c["reasoning_effort"] == "low" for c in gen_calls)


def test_harness_stops_a_generator_whose_model_is_unavailable(harness, indexed_lecture, lecture_llm_client,
                                                              session_factory):
    from tests.fakes import FakeProvider

    lecture_llm_client._providers["ollama"] = FakeProvider(
        "ollama", script=[ProviderError("unavailable", "refused", error_type="APIConnectionError")])
    h, lines = harness
    res = h.run(golden_set="g", items=_items(), lecture_id=indexed_lecture, generators=["finetuned"],
                retrieval=False)
    with session_factory() as db:
        run = db.get(EvalRun, res.generator_runs["finetuned"])
        assert run.status == "failed" and "MODEL_UNAVAILABLE" in run.error
        assert run.metrics_json["errors"] == {"MODEL_UNAVAILABLE": 1}
    assert any("stopping" in line for line in lines)


def test_judge_error_is_recorded_not_fatal(harness, indexed_lecture, fake_llm, session_factory):
    fake_llm.fail["eval_faithfulness"] = ProviderError("bad_request", "nope", error_type="BadRequestError")
    h, _ = harness
    res = h.run(golden_set="g", items=_items()[:1], lecture_id=indexed_lecture, generators=["cloud"],
                retrieval=False)
    with session_factory() as db:
        run = db.get(EvalRun, res.generator_runs["cloud"])
        assert run.status == "ok" and run.metrics_json["judge"]["errors"] == 1
        assert run.metrics_json["faithfulness"] is None


def test_harness_setup_errors(harness, settings):
    h, _ = harness
    with pytest.raises(EvalSetupError):
        h.run(golden_set="g", items=_items(), lecture_id=uuid.uuid4(), generators=["cloud"])


# ---------------------------------------------------------------------------- offline import


def _offline_file(path, *, subset=False):
    model = {"model": "m", "n_items": 2, "gqa": {"accuracy": 0.5}, "latency_ms": {"mean": 1.0}}
    data = {"backend": "hf", "created_at": "2026-11-08T10:00:00Z", "n_items": 500, "items_fingerprint": "abc",
            "prompt_versions": {"rag_answer": "rag_answer@v1"}, "models": {"base": model, "finetuned": model}}
    if subset:
        data |= {"subset": {"n": 50, "of_items": 500, "ids": ["x"]}, "backend": "ollama"}
    path.write_text(json.dumps(data), encoding="utf-8")


def test_offline_import_is_verbatim_and_idempotent(tmp_path, db):
    _offline_file(tmp_path / "eval_hf.json")
    _offline_file(tmp_path / "eval_ollama_subset50.json", subset=True)
    assert import_all(db, tmp_path) == {"eval_hf.json": 2, "eval_ollama_subset50.json": 2}
    assert import_all(db, tmp_path) == {"eval_hf.json": 0, "eval_ollama_subset50.json": 0}
    runs = db.scalars(select(EvalRun)).all()
    assert {(r.golden_set, r.generator) for r in runs} == {
        ("sciq_test_500", "base"), ("sciq_test_500", "finetuned"),
        ("sciq_test_subset50", "base"), ("sciq_test_subset50", "finetuned")}
    assert all(r.source == "offline_import" and r.metrics_json["gqa"]["accuracy"] == 0.5 for r in runs)
    assert "ids" not in runs[0].config_json["subset"] if runs[0].config_json["subset"] else True
    assert import_all(db, tmp_path / "nowhere") == {"eval_hf.json": "missing", "eval_ollama_subset50.json": "missing"}
    assert import_file(db, tmp_path / "eval_hf.json") == []


def test_eval_api_runs_detail_and_compare(client, auth_headers, harness, indexed_lecture, db, tmp_path):
    h, _ = harness
    h.run(golden_set="g1", items=_items(), lecture_id=indexed_lecture, generators=["cloud"])
    _offline_file(tmp_path / "eval_hf.json")
    import_all(db, tmp_path)
    runs = client.get("/api/llmops/eval/runs", headers=auth_headers).json()
    assert {r["source"] for r in runs} == {"harness", "offline_import"}
    cloud = next(r for r in runs if r["generator"] == "cloud")
    assert cloud["lecture_title"] == "Cell energy"
    detail = client.get(f"/api/llmops/eval/runs/{cloud['id']}", headers=auth_headers).json()
    assert len(detail["items"]) == 3 and detail["items"][0]["metrics"] is not None
    cmp_ = client.get("/api/llmops/eval/compare", headers=auth_headers).json()
    assert cmp_["golden_set"] == "g1" and cmp_["retrieval"]["generator"] == "retrieval"
    assert [g["generator"] for g in cmp_["generators"]] == ["cloud"]
    assert {o["generator"] for o in cmp_["offline"]} == {"base", "finetuned"}
