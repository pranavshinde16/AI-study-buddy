"""Quizzes, attempts, flashcards and per-topic mastery."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, JSONType, UUIDPrimaryKey


class Quiz(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "quizzes"

    lecture_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lectures.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    difficulty: Mapped[str | None] = mapped_column(String(16))
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # request settings (types, adaptive, ...)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(200))


class QuizQuestion(UUIDPrimaryKey, Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (UniqueConstraint("quiz_id", "idx", name="uq_quiz_questions_quiz_idx"),)

    quiz_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))  # mcq | true_false | short_answer
    difficulty: Mapped[str] = mapped_column(String(16))  # easy | medium | hard
    topic: Mapped[str | None] = mapped_column(String(300))
    question: Mapped[str] = mapped_column(Text)
    options_json: Mapped[list[str] | None] = mapped_column(JSONType)
    answer: Mapped[Any] = mapped_column(JSONType)  # option letter, bool, or reference text
    explanation: Mapped[str | None] = mapped_column(Text)
    source_start: Mapped[float | None] = mapped_column(Float)  # seconds, from transcript segments


class QuizAttempt(UUIDPrimaryKey, Base):
    __tablename__ = "quiz_attempts"

    quiz_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)
    total: Mapped[int] = mapped_column(Integer)
    percent: Mapped[float] = mapped_column(Float)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AttemptAnswer(UUIDPrimaryKey, Base):
    __tablename__ = "attempt_answers"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("quiz_attempts.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("quiz_questions.id", ondelete="CASCADE"))
    response: Mapped[Any] = mapped_column(JSONType)
    correct: Mapped[bool] = mapped_column(Boolean)
    graded_by: Mapped[str] = mapped_column(String(32))  # rule | llm | embedding
    feedback: Mapped[str | None] = mapped_column(Text)


class Flashcard(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "flashcards"

    lecture_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lectures.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(String(300))
    box: Mapped[int] = mapped_column(Integer, default=1)  # Leitner box 1..5
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TopicMastery(UUIDPrimaryKey, Base):
    __tablename__ = "topic_mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "lecture_id", "topic", name="uq_topic_mastery_user_lecture_topic"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lecture_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lectures.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(String(300))
    score_ema: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
