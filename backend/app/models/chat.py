"""Chat sessions/messages and the per-question RAG log (Phase 7)."""

import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, JSONType, UUIDPrimaryKey


class ChatSession(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "chat_sessions"

    lecture_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lectures.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(300))


class ChatMessage(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    sources_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType)
    answerable: Mapped[bool | None] = mapped_column(Boolean)
    model: Mapped[str | None] = mapped_column(String(200))


class QALog(UUIDPrimaryKey, CreatedAt, Base):
    """One row per /ask or /chat question: retrieval scores, refusal reason, end-to-end latency
    (metric M4) and which generator answered. SET NULL keeps the metrics after deletions."""

    __tablename__ = "qa_logs"

    lecture_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lectures.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("chat_sessions.id", ondelete="SET NULL"))
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("chat_messages.id", ondelete="SET NULL"))
    endpoint: Mapped[str] = mapped_column(String(16))  # ask | chat
    generator: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    question: Mapped[str] = mapped_column(Text)
    rewritten_question: Mapped[str | None] = mapped_column(Text)
    answerable: Mapped[bool | None] = mapped_column(Boolean)
    refusal_reason: Mapped[str | None] = mapped_column(String(32))  # below_threshold | not_in_chunks
    top_score: Mapped[float | None] = mapped_column(Float)
    min_score: Mapped[float] = mapped_column(Float)
    scores_json: Mapped[list[float] | None] = mapped_column(JSONType)
    retrieval_ms: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))  # ok | error
    error_code: Mapped[str | None] = mapped_column(String(64))
