"""Shapes for flashcard decks and reviews (IMPLEMENTATION_PLAN §6)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GenerateDeckRequest(BaseModel):
    regenerate: bool = Field(False, description="true = replace the deck (and its review progress) with a new one")


class FlashcardOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    kind: Literal["definition", "concept"]
    front: str
    back: str
    topic: str | None
    timestamp: float | None = Field(description="Where the lecture explains this (seconds); from the transcript")
    box: int = Field(description="Leitner box 1-5 (higher = known better)")
    due_at: datetime
    due: bool = Field(description="true if the card is due for review now")
    last_reviewed_at: datetime | None


class DeckMeta(BaseModel):
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    definition_cards: int | None = None
    concept_cards: int | None = None
    dropped: dict[str, int] = {}
    batches: int | None = None
    llm_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    llm_latency_ms: float | None = None
    generated_at: datetime | None = None


class DeckOut(BaseModel):
    lecture_id: uuid.UUID
    total: int
    due: int
    cards: list[FlashcardOut]
    cached: bool | None = Field(None, description="POST only: true if the stored deck was returned (no LLM calls)")
    meta: DeckMeta | None = Field(None, description="POST only, when a new deck was generated")


class ReviewRequest(BaseModel):
    knew: bool = Field(description="true = I knew it (move up a box); false = I didn't (back to box 1)")
