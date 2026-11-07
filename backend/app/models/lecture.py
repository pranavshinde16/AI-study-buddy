"""Lectures and everything derived directly from their audio: segments, chunks, outputs.

Timestamps are stored as `start_sec` / `end_sec` (seconds from the start of the lecture);
they always come from ASR transcript segments, never from an LLM (CLAUDE.md rule 3).
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, JSONType, UUIDPrimaryKey


class LectureStatus(StrEnum):
    """Pipeline stages, in order (IMPLEMENTATION_PLAN §6)."""

    UPLOADED = "uploaded"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    INDEXING = "indexing"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class Lecture(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "lectures"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    original_filename: Mapped[str | None] = mapped_column(String(500))
    media_path: Mapped[str | None] = mapped_column(String(1000))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    language: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default=LectureStatus.UPLOADED, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage_detail: Mapped[str | None] = mapped_column(String(300))
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("lecture_id", "idx", name="uq_transcript_segments_lecture_idx"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lecture_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lectures.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    start_sec: Mapped[float] = mapped_column(Float)
    end_sec: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)


class Chunk(UUIDPrimaryKey, Base):
    """Retrieval window over transcript segments; the embedding lives in ChromaDB under `vector_id`."""

    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("lecture_id", "idx", name="uq_chunks_lecture_idx"),)

    lecture_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lectures.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    start_sec: Mapped[float] = mapped_column(Float)
    end_sec: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    vector_id: Mapped[str | None] = mapped_column(String(100))


class OutputKind(StrEnum):
    SUMMARY = "summary"
    NOTES = "notes"
    MINDMAP = "mindmap"


class LectureOutput(UUIDPrimaryKey, CreatedAt, Base):
    """Cached generation results (summary, notes, mind map); one row per lecture and kind."""

    __tablename__ = "lecture_outputs"
    __table_args__ = (UniqueConstraint("lecture_id", "kind", name="uq_lecture_outputs_lecture_kind"),)

    lecture_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lectures.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONType)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(200))
