"""Shapes for /ask, /chat, chat history and /models (IMPLEMENTATION_PLAN §6).

`model` names an answer generator from the registry: "cloud" | "finetuned" | "base", or any
generator added through ANSWER_GENERATORS. An unknown name returns 422 UNKNOWN_GENERATOR
(GET /api/models lists the valid ones). Times are seconds from the start of the lecture,
taken from the transcript segments of each chunk.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

GENERATOR_FIELD = Field(
    "cloud",
    min_length=1,
    max_length=64,
    description='Answer generator: "cloud" | "finetuned" | "base" (or one added via ANSWER_GENERATORS)',
    examples=["cloud", "finetuned", "base"],
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, description="Your question about this lecture")
    model: str = GENERATOR_FIELD


class SourceOut(BaseModel):
    chunk_id: str = Field(description='Label used in the answer, e.g. "C2"')
    chunk_idx: int = Field(description="Index of the chunk in the lecture")
    start: float
    end: float
    excerpt: str
    score: float = Field(description="Cosine similarity of the chunk to the question (1 - distance)")
    cited: bool = Field(description="true if the answer cites it; false for the closest parts shown with a refusal")


class AskMeta(BaseModel):
    generator: str
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    rewritten_question: str | None = None
    refusal_reason: str | None = Field(None, description="below_threshold | not_in_chunks | null")
    top_score: float | None = None
    scores: list[float] = []
    min_score: float
    top_k: int
    retrieval_ms: float
    latency_ms: float = Field(description="End to end, including retrieval (metric M4)")
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    citations_dropped: list[str] = Field([], description="Cited ids that were not given to the model (removed)")
    citation_check: str = Field("ok", description="ok | none_valid (no valid citation: all chunks shown) | n/a")
    indexed_now: bool = Field(False, description="true if the lecture was indexed for this question")
    chunks: int = 0


class AskResponse(BaseModel):
    answer: str
    answerable: bool
    sources: list[SourceOut]
    meta: AskMeta


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: uuid.UUID | None = Field(None, description="null = start a new session")
    model: str = GENERATOR_FIELD


class ChatResponse(AskResponse):
    session_id: uuid.UUID
    message_id: uuid.UUID
    question: str
    rewritten_question: str | None = Field(None, description="Standalone question used for retrieval (follow-ups)")


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    sources: list[SourceOut]
    answerable: bool | None
    refusal_reason: str | None = Field(
        None, description="Assistant refusals: below_threshold | not_in_chunks (from qa_logs); null otherwise"
    )
    model: str | None
    created_at: datetime


class ChatHistoryOut(BaseModel):
    session_id: uuid.UUID
    lecture_id: uuid.UUID
    title: str | None
    created_at: datetime
    messages: list[ChatMessageOut]


class ChatSessionOut(BaseModel):
    session_id: uuid.UUID
    title: str | None
    created_at: datetime
    messages: int


class GeneratorOut(BaseModel):
    name: str
    provider: str
    model: str
    description: str
