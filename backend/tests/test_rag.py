"""RAG service and generator registry, without HTTP: query prefix on queries only, threshold
refusal without an LLM call, model refusal, citation check, follow-up rewrite, the registry
(built-ins, config-added and overridden generators) and Ollama errors. No network."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import GeneratorConfig
from app.models.lecture import Lecture, TranscriptSegment
from app.models.llmops import LLMCall
from app.models.user import User
from app.services.llm.errors import ModelUnavailableError
from app.services.llm.generators import GeneratorRegistry, UnknownGeneratorError
from app.services.llm.providers import ProviderError
from app.services.rag import RagService, check_citations, refusal_text
from app.services.vectorstore import Hit
from tests.fakes import FakeProvider

PREFIX = "Represent this sentence for searching relevant passages: "


@pytest.fixture
def lecture(db):
    user = User(email="rag@example.com", password_hash="x")
    db.add(user)
    db.flush()
    lec = Lecture(user_id=user.id, title="Cell energy", status="transcribed", progress=100)
    db.add(lec)
    db.flush()
    db.add_all(TranscriptSegment(lecture_id=lec.id, idx=i, start_sec=i * 10.0, end_sec=i * 10.0 + 9.5,
                                 text=f"sentence {i} about how cells turn food into energy") for i in range(30))
    db.commit()
    return lec


@pytest.fixture
def indexed(lecture, indexer, db):
    indexer.index(db, lecture.id, lecture.user_id)
    return lecture


def _ask(rag, lec, question="How do cells turn food into energy?", generator="cloud", history=()):
    return rag.answer(lecture_id=lec.id, user_id=lec.user_id, title=lec.title, question=question,
                      generator=generator, history=history)


def _calls(session_factory, task):
    with session_factory() as s:
        return list(s.scalars(select(LLMCall).where(LLMCall.task == task)))


def test_query_prefix_is_added_to_queries_only(indexed, rag, fake_embedder, session_factory):
    stored = [t for call in fake_embedder.calls for t in call]
    assert stored and not any(t.startswith(PREFIX.strip()) for t in stored)  # chunks: no prefix
    fake_embedder.calls.clear()
    _ask(rag, indexed)
    assert fake_embedder.calls == [[PREFIX + "How do cells turn food into energy?"]]
    assert {c.task for c in _calls(session_factory, "rag_query")} == {"rag_query"}
    assert len(_calls(session_factory, "rag_index")) == 1


def test_grounded_answer_with_valid_citations_and_chunk_timestamps(indexed, rag, fake_llm, settings):
    res = _ask(rag, indexed)
    assert res.answerable is True and res.refusal_reason is None
    assert "[C1]" in res.answer and "C9" not in res.answer  # invalid citation removed from the text
    assert res.citations_dropped == ["C9"] and res.citation_check == "ok"
    assert [s.chunk_id for s in res.sources] == ["C1"] and res.sources[0].cited is True
    src = res.sources[0]
    assert src.start % 10 == 0 and src.end > src.start  # chunk times = segment times
    assert res.top_score >= settings.rag_min_score and res.scores == sorted(res.scores, reverse=True)
    assert res.prompt_version == "rag_answer@v1" and res.generator == "cloud" and res.provider == "groq"
    assert fake_llm.tasks == ["rag_answer"]
    assert "[C1]" in fake_llm.user_messages[0] and "timestamp" not in fake_llm.user_messages[0].lower()


def test_below_threshold_refuses_without_an_llm_call(indexed, rag, fake_llm, monkeypatch):
    low = [Hit(f"x:{i}", 0.12 - i * 0.01, f"text {i}", {"idx": i, "start": i * 50.0, "end": i * 50.0 + 40})
           for i in range(5)]
    monkeypatch.setattr(rag.store, "query", lambda *_a, **_k: low)
    res = _ask(rag, indexed, question="Who won the 2022 World Cup?")
    assert res.answerable is False and res.refusal_reason == "below_threshold"
    assert res.answer.startswith("This isn't covered in the lecture.") and "00:00–00:40" in res.answer
    assert len(res.sources) == 3 and not any(s.cited for s in res.sources)
    assert res.top_score == 0.12 and fake_llm.tasks == []  # no LLM call at all


def test_model_can_refuse_above_the_threshold(indexed, rag, fake_llm):
    fake_llm.rag_answerable = False
    res = _ask(rag, indexed)
    assert res.answerable is False and res.refusal_reason == "not_in_chunks"
    assert res.answer.startswith("This isn't covered in the lecture.")
    assert fake_llm.tasks == ["rag_answer"] and not any(s.cited for s in res.sources)


def test_no_valid_citation_shows_all_chunks(indexed, rag, fake_llm):
    fake_llm.rag_citations = ["C42"]
    res = _ask(rag, indexed)
    assert res.answerable is True and res.citation_check == "none_valid" and res.citations_dropped == ["C42"]
    assert len(res.sources) == len(res.scores) and not any(s.cited for s in res.sources)


def test_follow_up_is_rewritten_before_retrieval(indexed, rag, fake_llm, fake_embedder):
    fake_embedder.calls.clear()
    res = _ask(rag, indexed, question="and why?", history=[("user", "What do cells make?"),
                                                           ("assistant", "Energy [C1].")])
    assert fake_llm.tasks == ["rag_rewrite", "rag_answer"]
    assert res.rewritten_question == "and why? (about how cells make energy)"
    assert fake_embedder.calls == [[PREFIX + res.rewritten_question]]
    assert "Student: What do cells make?" in fake_llm.user_messages[0]
    assert res.llm_calls == 2


def test_check_citations_helper():
    text, valid, dropped = check_citations("A [C2] and [c1] but not [C7].", ["C2", "c3"], ["C1", "C2", "C3"])
    assert text == "A [C2] and [C1] but not." and valid == ["C1", "C2", "C3"] and dropped == ["C7"]
    assert refusal_text([]) == "This isn't covered in the lecture."


# ---------------------------------------------------------------------------- registry


def test_registry_built_ins(settings, lecture_llm_client):
    reg = GeneratorRegistry(settings, lecture_llm_client)
    assert reg.names() == ["cloud", "finetuned", "base"]
    cloud, ft, base = reg.get("cloud"), reg.get("finetuned"), reg.get("base")
    assert (cloud.provider, cloud.model, cloud.max_retries) == ("groq", settings.llm_model, None)
    assert (ft.provider, ft.model, ft.max_retries) == ("ollama", settings.finetuned_model_tag, 0)
    assert (base.provider, base.model) == ("ollama", settings.base_slm_model_tag)
    with pytest.raises(UnknownGeneratorError) as exc:
        reg.get("gpt-9")
    assert exc.value.status_code == 422 and exc.value.details["available"] == reg.names()


def test_generators_can_be_added_and_overridden_through_config(settings, lecture_llm_client, indexed, embedding_client,
                                                              vector_store, session_factory):
    settings.answer_generators = {
        "small": GeneratorConfig(provider="groq", model="openai/gpt-oss-20b", description="Smaller Groq model"),
        "base": GeneratorConfig(provider="ollama", model="qwen3:0.6b"),
    }
    reg = GeneratorRegistry(settings, lecture_llm_client)
    assert reg.names() == ["cloud", "finetuned", "base", "small"]
    assert reg.get("base").model == "qwen3:0.6b"
    rag = RagService(settings, embedding_client, vector_store, reg)
    res = _ask(rag, indexed, generator="small")
    assert res.generator == "small" and res.answerable
    rows = _calls(session_factory, "rag_answer")
    assert [(r.provider, r.model) for r in rows] == [("groq", "openai/gpt-oss-20b")]


def test_ollama_down_is_a_clear_503_without_retries(indexed, rag, lecture_llm_client, session_factory):
    ollama = FakeProvider("ollama", script=[ProviderError("unavailable", "Connection refused",
                                                          error_type="APIConnectionError")])
    lecture_llm_client._providers["ollama"] = ollama
    with pytest.raises(ModelUnavailableError) as exc:
        _ask(rag, indexed, generator="finetuned")
    assert exc.value.status_code == 503 and "Ollama is not running" in exc.value.message
    assert "ollama serve" in exc.value.message
    assert len(ollama.calls) == 1  # 0 retries for the local model
    assert [(r.provider, r.status) for r in _calls(session_factory, "rag_answer")] == [("ollama", "unavailable")]


def test_ollama_model_missing_message(indexed, rag, lecture_llm_client, settings):
    lecture_llm_client._providers["ollama"] = FakeProvider(
        "ollama", script=[ProviderError("model_not_found", "404", error_type="NotFoundError")])
    with pytest.raises(ModelUnavailableError) as exc:
        _ask(rag, indexed, generator="base")
    assert f"Model '{settings.base_slm_model_tag}' is not installed in Ollama" in exc.value.message


def test_think_blocks_from_qwen_are_ignored(indexed, rag, lecture_llm_client):
    from tests.fakes import ok

    lecture_llm_client._providers["ollama"] = FakeProvider("ollama", script=[
        ok('<think>The user asks {about} energy...</think>{"answerable": true, "answer": "Energy [C1].", '
           '"citations": ["C1"]}')])
    res = _ask(rag, indexed, generator="finetuned")
    assert res.answerable and res.answer == "Energy [C1]." and res.provider == "ollama"


def test_index_is_rebuilt_when_vectors_are_missing(indexed, indexer, db, vector_store):
    assert indexer.ensure_indexed(db, indexed.id, indexed.user_id).indexed_now is False
    vector_store.delete_lecture(indexed.id)  # e.g. CHROMA_DIR was wiped
    again = indexer.ensure_indexed(db, indexed.id, indexed.user_id)
    assert again.indexed_now is True and vector_store.count(indexed.id) == again.chunks > 0


def test_unknown_lecture_id_has_no_hits(rag):
    assert rag.retrieve(uuid.uuid4(), "anything") == []
