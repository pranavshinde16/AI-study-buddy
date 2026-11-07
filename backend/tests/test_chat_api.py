"""/ask, /chat, chat history, /models and the qa_logs table over HTTP. Real in-memory Chroma,
fake embedder and fake LLM (no network)."""

import uuid

import pytest
from sqlalchemy import select

from app.models.chat import ChatMessage, QALog
from app.models.lecture import Chunk, Lecture
from app.services.llm.providers import ProviderError
from app.services.vectorstore import Hit
from app.workers.pipeline import mark_interrupted
from tests.fakes import FakeProvider

Q = "How do cells turn food into energy?"


def _ask(client, headers, lid, question=Q, model="cloud"):
    return client.post(f"/api/lectures/{lid}/ask", headers=headers, json={"question": question, "model": model})


def _logs(db):
    db.expire_all()
    return list(db.scalars(select(QALog).order_by(QALog.created_at)))


def test_ask_indexes_lazily_and_answers_with_sources(client, auth_headers, make_ready_lecture, db, vector_store):
    lid = make_ready_lecture(summarize=False)  # a pre-Phase-7 lecture: transcript but no index
    assert vector_store.count(lid) == 0
    r = _ask(client, auth_headers, lid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answerable"] is True and "[C1]" in body["answer"]
    assert body["meta"]["indexed_now"] is True and body["meta"]["chunks"] >= 1
    assert body["meta"]["refusal_reason"] is None and body["meta"]["citations_dropped"] == ["C9"]
    assert body["meta"]["prompt_version"] == "rag_answer@v1" and body["meta"]["generator"] == "cloud"
    src = body["sources"][0]
    chunk = db.scalar(select(Chunk).where(Chunk.lecture_id == lid, Chunk.idx == src["chunk_idx"]))
    assert (src["start"], src["end"]) == (chunk.start_sec, chunk.end_sec)  # times from the transcript
    assert src["cited"] is True and 0 < src["score"] <= 1
    assert vector_store.count(lid) == body["meta"]["chunks"]

    again = _ask(client, auth_headers, lid).json()
    assert again["meta"]["indexed_now"] is False

    logs = _logs(db)
    assert len(logs) == 2 and all(l.endpoint == "ask" and l.status == "ok" and l.answerable for l in logs)
    assert logs[0].top_score == body["meta"]["top_score"] and logs[0].latency_ms is not None
    assert logs[0].min_score == body["meta"]["min_score"] and logs[0].scores_json == body["meta"]["scores"]


def test_off_topic_question_is_refused_with_low_scores(client, auth_headers, make_ready_lecture, rag, fake_llm,
                                                       monkeypatch, db):
    """IMPLEMENTATION_PLAN Phase 7 check: a fake retriever with low scores -> answerable:false."""
    lid = make_ready_lecture()
    n_tasks = len(fake_llm.tasks)
    low = [Hit("x:0", 0.08, "sentence 3 about cells", {"idx": 3, "start": 30.0, "end": 39.5})]
    monkeypatch.setattr(rag.store, "query", lambda *_a, **_k: low)
    r = _ask(client, auth_headers, lid, question="Who won the 2022 World Cup?")
    body = r.json()
    assert r.status_code == 200 and body["answerable"] is False
    assert body["meta"]["refusal_reason"] == "below_threshold"
    assert body["answer"] == "This isn't covered in the lecture. The closest parts of the lecture are at 00:30–00:39."
    assert body["sources"][0]["cited"] is False and body["sources"][0]["start"] == 30.0
    assert len(fake_llm.tasks) == n_tasks  # no LLM call
    log = _logs(db)[-1]
    assert (log.answerable, log.refusal_reason, log.top_score) == (False, "below_threshold", 0.08)


def test_model_refusal_is_returned(client, auth_headers, make_ready_lecture, fake_llm):
    lid = make_ready_lecture()
    fake_llm.rag_answerable = False
    body = _ask(client, auth_headers, lid).json()
    assert body["answerable"] is False and body["meta"]["refusal_reason"] == "not_in_chunks"


def test_unknown_generator_and_validation(client, auth_headers, make_ready_lecture, settings):
    lid = make_ready_lecture()
    r = _ask(client, auth_headers, lid, model="gpt-9")
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_GENERATOR"
    assert r.json()["error"]["details"]["available"] == ["cloud", "finetuned", "base"]
    assert _ask(client, auth_headers, lid, question="").status_code == 422
    long = _ask(client, auth_headers, lid, question="x" * (settings.rag_max_question_chars + 1))
    assert long.status_code == 422


def test_finetuned_without_ollama_is_503(client, auth_headers, make_ready_lecture, lecture_llm_client, db):
    lid = make_ready_lecture()
    lecture_llm_client._providers["ollama"] = FakeProvider(
        "ollama", script=[ProviderError("unavailable", "refused", error_type="APIConnectionError")])
    r = _ask(client, auth_headers, lid, model="finetuned")
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "MODEL_UNAVAILABLE" and "Ollama" in err["message"]
    log = _logs(db)[-1]
    assert (log.status, log.error_code, log.generator) == ("error", "MODEL_UNAVAILABLE", "finetuned")


def test_ask_needs_a_transcript_and_not_indexing(client, auth_headers, make_ready_lecture, db):
    lid = make_ready_lecture(summarize=False)
    lec = db.get(Lecture, lid)
    lec.status = "transcribing"
    db.commit()
    r = _ask(client, auth_headers, lid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "LECTURE_NOT_READY"
    lec.status = "indexing"
    db.commit()
    r = _ask(client, auth_headers, lid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INDEXING_IN_PROGRESS"


def test_chat_session_follow_up_and_history(client, auth_headers, make_ready_lecture, fake_llm, db):
    lid = make_ready_lecture()
    first = client.post(f"/api/lectures/{lid}/chat", headers=auth_headers, json={"message": Q})
    assert first.status_code == 200, first.text
    f = first.json()
    assert f["rewritten_question"] is None and f["answerable"] is True  # first turn: nothing to rewrite
    sid = f["session_id"]

    fake_llm.tasks.clear()
    second = client.post(f"/api/lectures/{lid}/chat", headers=auth_headers,
                         json={"message": "and why?", "session_id": sid}).json()
    assert second["session_id"] == sid
    assert second["rewritten_question"] == "and why? (about how cells make energy)"
    assert fake_llm.tasks == ["rag_rewrite", "rag_answer"]
    assert f"Student: {Q}\nAssistant: From the lecture" in fake_llm.user_messages[-2]

    hist = client.get(f"/api/lectures/{lid}/chat/{sid}", headers=auth_headers).json()
    assert [m["role"] for m in hist["messages"]] == ["user", "assistant", "user", "assistant"]
    assert [m["content"] for m in hist["messages"]][::2] == [Q, "and why?"]
    assert hist["messages"][1]["sources"] and hist["messages"][1]["answerable"] is True
    assert hist["messages"][1]["model"].startswith("cloud:")

    sessions = client.get(f"/api/lectures/{lid}/chat", headers=auth_headers).json()
    assert [(s["session_id"], s["messages"]) for s in sessions] == [(sid, 4)]
    logs = [l for l in _logs(db) if l.endpoint == "chat"]
    assert len(logs) == 2 and logs[1].rewritten_question and logs[1].message_id is not None


def test_history_window_is_limited(client, auth_headers, make_ready_lecture, fake_llm, settings):
    settings.rag_history_turns = 1
    lid = make_ready_lecture()
    sid = None
    for msg in ("one?", "two?", "three?"):
        body = {"message": msg} | ({"session_id": sid} if sid else {})
        sid = client.post(f"/api/lectures/{lid}/chat", headers=auth_headers, json=body).json()["session_id"]
    rewrite_prompt = fake_llm.user_messages[-2]
    assert "Student: two?" in rewrite_prompt and "one?" not in rewrite_prompt


def test_chat_ownership_and_unknown_session(client, auth_headers, make_ready_lecture, make_user):
    lid = make_ready_lecture()
    sid = client.post(f"/api/lectures/{lid}/chat", headers=auth_headers, json={"message": "Q?"}).json()["session_id"]
    r = client.post(f"/api/lectures/{lid}/chat", headers=auth_headers,
                    json={"message": "Q?", "session_id": str(uuid.uuid4())})
    assert r.status_code == 404 and r.json()["error"]["code"] == "CHAT_SESSION_NOT_FOUND"

    make_user("eve@example.com", "another-password-123", "Eve")
    tok = client.post("/api/auth/login", json={"email": "eve@example.com", "password": "another-password-123"})
    eve = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    assert client.get(f"/api/lectures/{lid}/chat/{sid}", headers=eve).status_code == 404
    assert _ask(client, eve, lid).status_code == 404
    assert client.post(f"/api/lectures/{lid}/chat", headers=eve, json={"message": "hi"}).status_code == 404


def test_models_lists_registry(client, auth_headers):
    body = client.get("/api/models", headers=auth_headers).json()
    assert [g["name"] for g in body] == ["cloud", "finetuned", "base"]
    assert body[0]["provider"] == "groq" and body[1]["provider"] == "ollama"
    assert client.get("/api/models").status_code == 401


def test_delete_lecture_removes_vectors_and_keeps_logs(client, auth_headers, make_ready_lecture, vector_store, db):
    lid = make_ready_lecture()
    _ask(client, auth_headers, lid)
    assert vector_store.count(lid) > 0
    assert client.delete(f"/api/lectures/{lid}", headers=auth_headers).status_code == 204
    assert vector_store.count(lid) == 0
    logs = _logs(db)
    assert len(logs) == 1 and logs[0].lecture_id is None  # metrics kept, unlinked


def test_startup_sweep_returns_indexing_to_transcribed(make_ready_lecture, session_factory, db):
    lid = make_ready_lecture(summarize=False)
    db.get(Lecture, lid).status = "indexing"
    db.commit()
    assert mark_interrupted(session_factory) == 1
    db.expire_all()
    lec = db.get(Lecture, lid)
    assert lec.status == "transcribed" and "first question" in lec.stage_detail


@pytest.mark.parametrize("endpoint", ["ask", "chat"])
def test_messages_store_sources(client, auth_headers, make_ready_lecture, db, endpoint):
    lid = make_ready_lecture()
    key = "question" if endpoint == "ask" else "message"
    client.post(f"/api/lectures/{lid}/{endpoint}", headers=auth_headers, json={key: Q})
    stored = list(db.scalars(select(ChatMessage)))
    assert (len(stored) == 2) is (endpoint == "chat")  # /ask is not stored as a chat
