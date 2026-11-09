"""LLMOps tables (IMPLEMENTATION_PLAN §7.1): every model call, pipeline stage and eval run."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, UUIDPrimaryKey


class LLMCall(UUIDPrimaryKey, Base):
    """One row per request sent to a model provider (LLM, ASR or embedding), success or not."""

    __tablename__ = "llm_calls"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    # SET NULL keeps the metrics after a user/lecture is deleted.
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lectures.id", ondelete="SET NULL"), index=True
    )
    task: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(200))  # model we asked for
    model_version: Mapped[str | None] = mapped_column(String(200))  # model string the provider returned
    prompt_id: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(Integer, default=1)  # 1 = first try; >1 = retry or JSON repair
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), index=True)  # ok | json_invalid | rate_limited | unavailable | error
    error_type: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    request_hash: Mapped[str | None] = mapped_column(String(64), index=True)


class PipelineRun(UUIDPrimaryKey, Base):
    __tablename__ = "pipeline_runs"

    lecture_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lectures.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    audio_sec: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))  # running | ok | failed
    error_message: Mapped[str | None] = mapped_column(Text)


class EvalRun(UUIDPrimaryKey, Base):
    """One evaluation run. `source` = "harness" (python -m eval.run on a golden set; one run per
    generator, plus one "retrieval" run for the shared retriever) or "offline_import" (a Phase 10
    finetune/results/eval_*.json file imported as is, generator = base | finetuned)."""

    __tablename__ = "eval_runs"

    golden_set: Mapped[str] = mapped_column(String(200))
    generator: Mapped[str] = mapped_column(String(32))  # cloud | finetuned | base | retrieval
    model: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(32), default="harness", server_default="harness")
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("lectures.id", ondelete="SET NULL"))
    n_items: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    prompt_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # filled only from real runs
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvalItem(UUIDPrimaryKey, Base):
    __tablename__ = "eval_items"

    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("lectures.id", ondelete="SET NULL"))
    item_key: Mapped[str | None] = mapped_column(String(100))  # golden-set `id`
    kind: Mapped[str | None] = mapped_column(String(32))  # on_topic | near_topic | off_topic
    refusal_reason: Mapped[str | None] = mapped_column(String(32))  # below_threshold | not_in_chunks
    top_score: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="ok", server_default="ok")  # ok | error
    question: Mapped[str] = mapped_column(Text)
    answerable: Mapped[bool] = mapped_column(Boolean)
    gold_start: Mapped[float | None] = mapped_column(Float)
    gold_end: Mapped[float | None] = mapped_column(Float)
    reference_answer: Mapped[str | None] = mapped_column(Text)
    predicted_answer: Mapped[str | None] = mapped_column(Text)
    predicted_answerable: Mapped[bool | None] = mapped_column(Boolean)
    retrieved_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
