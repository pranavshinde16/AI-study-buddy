"""Response shapes for /api/llmops/* (Phase 11). Every value is computed from logged rows."""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class FiltersOut(BaseModel):
    date_from: date | None
    date_to: date | None
    task: str | None
    generator: str | None
    include_eval: bool


class LatencyStats(BaseModel):
    n: int
    p50_ms: float | None
    p95_ms: float | None
    mean_ms: float | None


class SummaryOut(BaseModel):
    filters: FiltersOut
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    cost_unknown_calls: int
    equivalent_cost_usd: float
    unpriced_calls: int
    failed_calls: int
    error_rate: float | None
    json_invalid_calls: int
    parse_failure_rate: float | None
    rtf_overall: float | None
    transcriptions: int
    questions: int
    qa_latency: LatencyStats
    first_call_at: datetime | None
    last_call_at: datetime | None
    pricing_checked: str


class TaskLatencyOut(LatencyStats):
    task: str
    provider: str
    model: str


class QALatencyOut(LatencyStats):
    generator: str
    answered: LatencyStats
    refused_by_model: LatencyStats
    refused_by_threshold: LatencyStats
    retrieval: LatencyStats


class UsageRowOut(BaseModel):
    key: str
    label: str
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    cost_unknown_calls: int
    equivalent_cost_usd: float
    unpriced_calls: int


class TranscriptionRunOut(BaseModel):
    lecture_id: uuid.UUID
    title: str | None
    started_at: datetime
    audio_sec: float
    processing_sec: float
    rtf: float


class TranscriptionOut(BaseModel):
    runs: list[TranscriptionRunOut]
    n: int
    total_audio_sec: float
    total_processing_sec: float
    rtf_overall: float | None
    rtf_median: float | None


class TaskErrorsOut(BaseModel):
    task: str
    requests: int
    failed: int
    json_invalid: int
    repair_failed: int
    rate_limited: int
    error_rate: float | None
    parse_failure_rate: float | None


class RecentErrorOut(BaseModel):
    ts: datetime
    task: str
    provider: str
    model: str
    status: str
    error_type: str | None
    error_message: str | None
    prompt_version: str | None
    attempt: int


class ErrorsOut(BaseModel):
    requests: int
    failed: int
    error_rate: float | None
    json_invalid: int
    by_task: list[TaskErrorsOut]
    recent: list[RecentErrorOut]


class RefusalsOut(BaseModel):
    generator: str
    questions: int
    answered: int
    below_threshold: int
    not_in_chunks: int
    errors: int
    refused: int
    refusal_rate: float | None
    threshold_share_of_refusals: float | None


class PromptMetricsOut(LatencyStats):
    prompt_version: str
    prompt_id: str | None
    task: str
    requests: int
    error_rate: float | None
    parse_failure_rate: float | None
    mean_input_tokens: float | None
    mean_output_tokens: float | None


class FilterOptionsOut(BaseModel):
    tasks: list[str]
    eval_tasks: list[str]
    generators: list[str]
    generators_with_questions: list[str]
    first_call_at: datetime | None
    last_call_at: datetime | None


class RegistryGeneratorOut(BaseModel):
    kind: str
    name: str
    provider: str
    model: str
    description: str
    version: str | None
    last_used_at: datetime | None
    digest: str | None
    size_bytes: int | None
    available: bool | None
    details: dict[str, Any]


class RegistryOtherOut(BaseModel):
    kind: str
    name: str
    provider: str
    model: str
    version: str | None
    last_used_at: datetime | None
    revision: str | None = None
    note: str | None = None


class PromptVersionOut(BaseModel):
    id: str
    version: str
    tag: str


class ModelRegistryOut(BaseModel):
    ollama_reachable: bool | None
    ollama_url: str
    generators: list[RegistryGeneratorOut]
    others: list[RegistryOtherOut]
    prompts: list[PromptVersionOut]


class EvalRunOut(BaseModel):
    id: uuid.UUID
    golden_set: str
    generator: str
    model: str | None
    source: str
    lecture_id: uuid.UUID | None
    lecture_title: str | None
    n_items: int | None
    status: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    prompt_versions: dict[str, Any] | None
    config: dict[str, Any] | None
    metrics: dict[str, Any] | None


class EvalItemOut(BaseModel):
    id: uuid.UUID
    item_key: str | None
    kind: str | None
    question: str
    answerable: bool
    gold_start: float | None
    gold_end: float | None
    reference_answer: str | None
    predicted_answer: str | None
    predicted_answerable: bool | None
    refusal_reason: str | None
    top_score: float | None
    latency_ms: float | None
    status: str
    retrieved: list[dict[str, Any]] | None
    metrics: dict[str, Any] | None


class EvalRunDetailOut(EvalRunOut):
    items: list[EvalItemOut]


class EvalCompareOut(BaseModel):
    golden_set: str | None
    golden_sets: list[str]
    retrieval: EvalRunOut | None
    generators: list[EvalRunOut]
    offline: list[EvalRunOut]
