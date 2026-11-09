"""Use cases for POST /ask, POST /chat and the chat history (Phase 7). Routers call these.

- The lecture must have a transcript (409 LECTURE_NOT_READY otherwise) and must not be in the
  middle of indexing (409 INDEXING_IN_PROGRESS).
- A lecture that has no index yet (transcribed before Phase 7) is indexed on its first question.
- /chat stores both turns in chat_sessions/chat_messages. The last RAG_HISTORY_TURNS pairs are
  used to rewrite a follow-up into a standalone question before retrieval.
- Every question, answered, refused or failed, writes one qa_logs row (retrieval scores,
  refusal reason, end-to-end latency, generator).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.models.chat import ChatMessage, ChatSession, QALog
from app.models.lecture import Lecture, LectureStatus
from app.models.user import User
from app.services.indexing import IndexResult, LectureIndexer
from app.services.lectures import TRANSCRIPT_READY, LectureNotReadyError, get_lecture
from app.services.rag import RagAnswer, RagService

log = structlog.get_logger(__name__)


class IndexingInProgressError(ConflictError):
    code = "INDEXING_IN_PROGRESS"


class QuestionTooLongError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_ERROR"


def _ready_lecture(db: Session, user: User, lecture_id: uuid.UUID, settings: Settings, question: str) -> Lecture:
    if len(question) > settings.rag_max_question_chars:
        raise QuestionTooLongError(f"The question is longer than {settings.rag_max_question_chars} characters")
    lecture = get_lecture(db, user, lecture_id)
    if lecture.status not in TRANSCRIPT_READY:
        raise LectureNotReadyError(
            "The transcript is not ready yet", details={"status": lecture.status, "progress": lecture.progress}
        )
    if lecture.status == LectureStatus.INDEXING:
        raise IndexingInProgressError("The lecture is being indexed for search; try again in a few seconds")
    return lecture


def _log(db: Session, *, lecture: Lecture, user: User, endpoint: str, generator: str, question: str,
         settings: Settings, result: RagAnswer | None = None, error: AppError | None = None,
         session_id: uuid.UUID | None = None, message_id: uuid.UUID | None = None) -> None:
    row = QALog(
        lecture_id=lecture.id, user_id=user.id, session_id=session_id, message_id=message_id, endpoint=endpoint,
        generator=generator, question=question, min_score=settings.rag_min_score,
        status="ok" if error is None else "error", error_code=error.code if error else None,
    )
    if result is not None:
        row.provider, row.model, row.prompt_version = result.provider, result.model, result.prompt_version
        row.rewritten_question, row.answerable = result.rewritten_question, result.answerable
        row.refusal_reason, row.top_score, row.scores_json = result.refusal_reason, result.top_score, result.scores
        row.retrieval_ms, row.latency_ms = result.retrieval_ms, result.latency_ms
    db.add(row)
    db.commit()


def _display_model(result: RagAnswer) -> str:
    """"generator:model" shown in a reopened chat. The Ollama digest (Phase 11) is kept in
    qa_logs/llm_calls for LLMOps but left out here, so the chat shows the same as before."""
    if not result.model:
        return result.generator
    return f"{result.generator}:{result.model.split('@sha256:', 1)[0]}"


def _run(db: Session, *, rag: RagService, indexer: LectureIndexer, settings: Settings, lecture: Lecture,
         user: User, question: str, generator: str, history: list[tuple[str, str]], endpoint: str,
         session_id: uuid.UUID | None = None) -> tuple[RagAnswer, IndexResult]:
    try:
        rag.generators.get(generator)  # 422 for an unknown name before indexing anything
        idx = indexer.ensure_indexed(db, lecture.id, user.id)
        result = rag.answer(lecture_id=lecture.id, user_id=user.id, title=lecture.title, question=question,
                            generator=generator, history=history)
    except AppError as exc:
        db.rollback()
        _log(db, lecture=lecture, user=user, endpoint=endpoint, generator=generator, question=question,
             settings=settings, error=exc, session_id=session_id)
        raise
    return result, idx


def _response(result: RagAnswer, idx: IndexResult, settings: Settings) -> dict[str, Any]:
    meta = result.meta() | {"min_score": settings.rag_min_score, "top_k": settings.rag_top_k,
                            "indexed_now": idx.indexed_now, "chunks": idx.chunks}
    return {
        "answer": result.answer,
        "answerable": result.answerable,
        "sources": [vars(s) for s in result.sources],
        "meta": meta,
    }


# ---------------------------------------------------------------------------- /ask


def ask(db: Session, user: User, lecture_id: uuid.UUID, *, question: str, generator: str, settings: Settings,
        rag: RagService, indexer: LectureIndexer) -> dict[str, Any]:
    question = question.strip()
    lecture = _ready_lecture(db, user, lecture_id, settings, question)
    result, idx = _run(db, rag=rag, indexer=indexer, settings=settings, lecture=lecture, user=user,
                       question=question, generator=generator, history=[], endpoint="ask")
    _log(db, lecture=lecture, user=user, endpoint="ask", generator=generator, question=question,
         settings=settings, result=result)
    return _response(result, idx, settings)


# ---------------------------------------------------------------------------- /chat


def _session(db: Session, user: User, lecture_id: uuid.UUID, session_id: uuid.UUID) -> ChatSession:
    s = db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id,
                                            ChatSession.lecture_id == lecture_id))
    if s is None:
        raise NotFoundError("Chat session not found", code="CHAT_SESSION_NOT_FOUND")
    return s


def messages_of(db: Session, session_id: uuid.UUID) -> list[ChatMessage]:
    return list(db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    ))


def chat(db: Session, user: User, lecture_id: uuid.UUID, *, message: str, session_id: uuid.UUID | None,
         generator: str, settings: Settings, rag: RagService, indexer: LectureIndexer) -> dict[str, Any]:
    message = message.strip()
    lecture = _ready_lecture(db, user, lecture_id, settings, message)
    if session_id is not None:
        session = _session(db, user, lecture_id, session_id)
        previous = messages_of(db, session.id)
    else:
        session = None
        previous = []
    history = [(m.role, m.content) for m in previous][-2 * settings.rag_history_turns:]

    result, idx = _run(db, rag=rag, indexer=indexer, settings=settings, lecture=lecture, user=user,
                       question=message, generator=generator, history=history, endpoint="chat",
                       session_id=session.id if session else None)

    if session is None:
        session = ChatSession(lecture_id=lecture.id, user_id=user.id, title=message[:300])
        db.add(session)
        db.flush()
    # Explicit times: the DB default (now()) is the same for both rows of one transaction on
    # PostgreSQL and has 1-second resolution on SQLite, which would scramble the history order.
    t = datetime.now(UTC)
    user_msg = ChatMessage(session_id=session.id, role="user", content=message, created_at=t)
    db.add(user_msg)
    reply = ChatMessage(session_id=session.id, role="assistant", content=result.answer, created_at=t + timedelta(microseconds=1),
                        sources_json=[vars(s) for s in result.sources], answerable=result.answerable,
                        model=_display_model(result))
    db.add(reply)
    db.commit()
    _log(db, lecture=lecture, user=user, endpoint="chat", generator=generator, question=message,
         settings=settings, result=result, session_id=session.id, message_id=reply.id)
    return {"session_id": session.id, "message_id": reply.id, "question": message,
            "rewritten_question": result.rewritten_question, **_response(result, idx, settings)}


def list_sessions(db: Session, user: User, lecture_id: uuid.UUID) -> list[dict[str, Any]]:
    get_lecture(db, user, lecture_id)
    sessions = db.scalars(select(ChatSession).where(ChatSession.lecture_id == lecture_id,
                                                    ChatSession.user_id == user.id)
                          .order_by(ChatSession.created_at.desc())).all()
    return [{"session_id": s.id, "title": s.title, "created_at": s.created_at,
             "messages": len(messages_of(db, s.id))} for s in sessions]


def get_history(db: Session, user: User, lecture_id: uuid.UUID, session_id: uuid.UUID) -> dict[str, Any]:
    get_lecture(db, user, lecture_id)
    s = _session(db, user, lecture_id, session_id)
    messages = messages_of(db, s.id)
    # The refusal reason lives in qa_logs (one row per answered question, linked to the reply).
    reply_ids = [m.id for m in messages if m.role == "assistant"]
    reasons = dict(
        db.execute(select(QALog.message_id, QALog.refusal_reason).where(QALog.message_id.in_(reply_ids))).all()
    ) if reply_ids else {}
    return {
        "session_id": s.id, "lecture_id": lecture_id, "title": s.title, "created_at": s.created_at,
        "messages": [{"id": m.id, "role": m.role, "content": m.content, "sources": m.sources_json or [],
                      "answerable": m.answerable, "refusal_reason": reasons.get(m.id), "model": m.model,
                      "created_at": m.created_at}
                     for m in messages],
    }
