"""Shapes for POST /lectures/{id}/summarize and GET /lectures/{id}/notes (IMPLEMENTATION_PLAN §6).

All times are seconds from the start of the lecture, looked up from transcript segments.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SummarizeRequest(BaseModel):
    regenerate: bool = Field(False, description="true = ignore the cached result and generate again")


class DefinitionOut(BaseModel):
    term: str
    definition: str
    timestamp: float | None = Field(description="Start of the segment where the term is explained; null if unknown")


class TopicOut(BaseModel):
    title: str
    start: float
    end: float
    notes_md: str
    key_points: list[str] = []


class GenerationMeta(BaseModel):
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    prompt_version: str | None = Field(None, description="Version of the summary prompt, e.g. summary@v1")
    prompt_versions: dict[str, str] = {}
    mode: str | None = Field(None, description="single_pass | map_reduce")
    windows: int | None = None
    llm_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    llm_latency_ms: float | None = None
    generated_at: datetime | None = None


class SummaryResponse(BaseModel):
    lecture_id: uuid.UUID
    summary: str
    key_takeaways: list[str]
    definitions: list[DefinitionOut]
    topics: list[TopicOut]
    revision_notes_md: str
    meta: GenerationMeta
    cached: bool = Field(description="true if this came from the cache (no LLM calls were made)")


class NotesResponse(BaseModel):
    lecture_id: uuid.UUID
    topics: list[TopicOut]
    meta: GenerationMeta
