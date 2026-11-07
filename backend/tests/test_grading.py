"""Answer grading: rules for MCQ/true-false, LLM rubric grading for short answers, and the
embedding-similarity fallback. Also the embedding client (fake embedder: no model download)."""

import sys
import uuid

import pytest
from sqlalchemy import select

from app.models.llmops import LLMCall
from app.services.embeddings import SentenceTransformerEmbedder, cosine
from app.services.grading import (
    GradingUnavailableError,
    ShortItem,
    grade_mcq,
    grade_true_false,
    normalise_choice,
)
from app.services.llm.providers import ProviderError
from tests.fakes import rate_limited


def _calls(session_factory, task=None):
    with session_factory() as s:
        q = select(LLMCall)
        if task:
            q = q.where(LLMCall.task == task)
        return list(s.scalars(q))


@pytest.mark.parametrize(
    ("response", "expected"),
    [("B", "B"), ("b", "B"), (" B) ", "B"), ("(b)", "B"), ("Rome", "B"), ("rome", "B"), ("E", None), (True, None)],
)
def test_normalise_choice(response, expected):
    assert normalise_choice(response, ["Paris", "Rome", "Oslo", "Bern"]) == expected


def test_rule_grading():
    opts = ["Paris", "Rome", "Oslo", "Bern"]
    assert grade_mcq("b", "B", opts).correct is True
    assert grade_mcq("A", "B", opts).correct is False
    assert grade_mcq("A", "B", opts).graded_by == "rule"
    assert grade_true_false("false", False).correct is True
    assert grade_true_false(True, False).score == 0.0


def _items():
    return [
        ShortItem("q1", "What do cells make?", "Cells make energy as ATP", ["energy"], "They produce energy"),
        ShortItem("q2", "Where?", "In the mitochondria", ["mitochondria"], "in the nucleus"),
    ]


def test_short_answers_graded_by_llm_in_one_request(grader, fake_llm, session_factory, settings):
    grades = grader.grade(_items(), lecture_id=None, user_id=None)
    assert grades["q1"].correct is True and grades["q1"].graded_by == "llm" and grades["q1"].score == 1.0
    assert grades["q2"].correct is False and grades["q2"].feedback == "Misses the key point."
    assert fake_llm.tasks == ["grading"]
    rows = _calls(session_factory, "grading")
    assert len(rows) == 1 and rows[0].prompt_version == "grade_short@v1" and rows[0].model == settings.judge_model


def test_empty_answers_need_no_model_call(grader, fake_llm, fake_embedder):
    grades = grader.grade([ShortItem("q1", "Q?", "ref", ["ref"], "   ")], lecture_id=None, user_id=None)
    assert grades["q1"].correct is False and grades["q1"].graded_by == "rule"
    assert fake_llm.tasks == [] and fake_embedder.calls == []


def test_falls_back_to_embeddings_when_llm_is_rate_limited(grader, fake_llm, fake_embedder, settings, session_factory):
    settings.llm_max_retries = 1
    fake_llm.fail["grading"] = rate_limited()
    items = [
        ShortItem("q1", "Q?", "cells turn food into energy", ["energy"], "cells turn food into energy quickly"),
        ShortItem("q2", "Q?", "cells turn food into energy", ["energy"], "volcanoes erupt lava"),
    ]
    grades = grader.grade(items, lecture_id=None, user_id=None)
    assert grades["q1"].graded_by == "embedding" and grades["q1"].correct is True
    assert grades["q2"].graded_by == "embedding" and grades["q2"].correct is False
    assert grades["q1"].score >= settings.short_answer_sim_threshold > grades["q2"].score
    assert "unavailable" in grades["q1"].feedback
    assert fake_llm.tasks == ["grading", "grading"]  # same provider retried, never another one
    assert len(fake_embedder.calls) == 1
    statuses = [r.status for r in _calls(session_factory, "grading")]
    assert statuses == ["rate_limited", "rate_limited"]
    emb = _calls(session_factory, "grading_embedding")
    assert len(emb) == 1 and emb[0].provider == "local" and emb[0].cost_usd == 0.0 and emb[0].status == "ok"


def test_items_the_llm_skips_are_graded_by_embeddings(grader, fake_llm, fake_embedder):
    fake_llm.grading_skip = {"q2"}
    grades = grader.grade(_items(), lecture_id=None, user_id=None)
    assert grades["q1"].graded_by == "llm" and grades["q2"].graded_by == "embedding"
    assert fake_embedder.calls == [["in the nucleus", "In the mitochondria"]]


def test_invalid_llm_output_falls_back(grader, fake_llm):
    fake_llm.invalid["grading"] = True
    grades = grader.grade(_items(), lecture_id=None, user_id=None)
    assert {g.graded_by for g in grades.values()} == {"embedding"}


def test_both_graders_failing_is_a_clear_503(grader, fake_llm, fake_embedder, settings, session_factory):
    settings.llm_max_retries = 0
    fake_llm.fail["grading"] = ProviderError("unavailable", "503", error_type="APIStatusError")
    fake_embedder.fail = RuntimeError("model file corrupt")
    with pytest.raises(GradingUnavailableError) as exc:
        grader.grade(_items(), lecture_id=None, user_id=None)
    assert exc.value.status_code == 503
    assert _calls(session_factory, "grading_embedding")[0].status == "error"


# ---------------------------------------------------------------------------- embedding client


def test_embedding_client_logs_a_local_free_call(embedding_client, session_factory):
    lid = uuid.uuid4()
    vecs = embedding_client.embed(["cells make energy", "cells make energy", "volcano"], task="embedding")
    assert len(vecs) == 3
    assert cosine(vecs[0], vecs[1]) == pytest.approx(1.0)
    assert cosine(vecs[0], vecs[2]) < 0.5
    rows = _calls(session_factory, "embedding")
    assert len(rows) == 1 and rows[0].provider == "local" and rows[0].model == "fake-embedder"
    assert rows[0].cost_usd == 0.0 and rows[0].latency_ms is not None
    assert embedding_client.embed([], task="embedding") == []
    assert lid  # unlinked call: no lecture needed


def test_model_load_happens_before_the_timed_encode(settings, session_factory):
    from app.services.embeddings import EmbeddingClient
    from app.services.llm.pricing import load_pricing
    from tests.fakes import FakeEmbedder

    order = []

    class LoadingEmbedder(FakeEmbedder):
        def load(self):
            order.append("load")

        def encode(self, texts):
            order.append("encode")
            return super().encode(texts)

    client = EmbeddingClient(settings, session_factory, load_pricing(), embedder=LoadingEmbedder())
    client.embed(["a"], task="embedding")
    assert order == ["load", "encode"]


def test_cosine_handles_zero_vectors():
    assert cosine([0, 0], [1, 0]) == 0.0
    assert cosine([1, 0], [2, 0]) == pytest.approx(1.0)


def test_real_embedder_is_lazy():
    """Creating the wrapper must not import torch or load the model (that happens on first encode)."""
    before = "sentence_transformers" in sys.modules
    emb = SentenceTransformerEmbedder("BAAI/bge-small-en-v1.5")
    assert emb.loaded is False
    assert ("sentence_transformers" in sys.modules) == before
