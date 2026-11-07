"""Flashcard deck generation (IMPLEMENTATION_PLAN §6 /flashcards, Phase 6).

A deck has two kinds of card:
    definition : one per definition in the Phase 5 summary (term -> definition). No LLM call;
                 the timestamp is the one already looked up from the transcript.
    concept    : written by the LLM from the transcript, batch by batch (same batches as the
                 quiz), in proportion to each batch's length.

No duplicates: every card's front is reduced to a key (lower case, punctuation and leading
question words such as "what is" / "define" removed). A card whose key matches an earlier
card or a definition term is dropped. Concept cards whose segment id is not in their batch
are dropped too (no timestamp is ever guessed).
"""

import re
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.generation.context import TopicSpan, allocate, build_batches, numbered, topic_of
from app.services.generation.summary import SegmentLike, _norm, _Usage
from app.services.llm.client import LLMClient
from app.services.llm.errors import LLMOutputInvalidError

_QUESTION_LEAD = re.compile(r"^(?:what|who|which|how|why|when|where)\s+(?:is|are|was|were|does|do|did)\s+")
_VERB_LEAD = re.compile(r"^(?:define|explain|describe|meaning of)\s+")
_ARTICLE = re.compile(r"^(?:the|a|an)\s+")
_TAIL = re.compile(r"\s+(?:mean|means|stand for|stands for|refer to|refers to)$")

MAX_FRONT, MAX_BACK = 300, 1200


class CardItem(BaseModel):
    front: str = Field(description="question, max 20 words")
    back: str = Field(description="answer, 1-3 sentences")
    segment_id: int = Field(description="id of the segment where the answer is explained")


class CardsOut(BaseModel):
    cards: list[CardItem]


@dataclass
class DraftCard:
    kind: str  # definition | concept
    front: str
    back: str
    topic: str | None
    source_start: float | None


@dataclass
class DeckDraft:
    cards: list[DraftCard]
    meta: dict[str, Any]


def card_key(front: str) -> str:
    """Normalised front used to detect duplicates ("What is a Neuron?" == "neuron")."""
    k = _norm(front)
    for pattern in (_QUESTION_LEAD, _VERB_LEAD, _ARTICLE, _TAIL):
        k = pattern.sub("", k).strip()
    return k


class FlashcardGenerator:
    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self.settings = settings
        self.llm = llm

    def generate(
        self,
        *,
        lecture_id: uuid.UUID,
        user_id: uuid.UUID | None,
        title: str,
        topics: Sequence[TopicSpan],
        segments: Sequence[SegmentLike],
        definitions: Sequence[dict[str, Any]],
        max_cards: int | None = None,
    ) -> DeckDraft:
        limit = max_cards or self.settings.flashcards_max_cards
        by_idx = {s.idx: s for s in segments if s.text.strip()}
        seen: set[str] = set()
        dropped: Counter = Counter()
        cards: list[DraftCard] = []

        # 1. definition cards (no LLM)
        for d in definitions:
            term, definition = str(d.get("term", "")).strip(), str(d.get("definition", "")).strip()
            key = card_key(term)
            if not term or not definition or not key:
                continue
            if key in seen:
                dropped["duplicate"] += 1
                continue
            if len(cards) >= limit:
                break
            seen.add(key)
            seg_id = d.get("segment_id")
            cards.append(DraftCard("definition", term[:MAX_FRONT], definition[:MAX_BACK],
                                   topic_of(topics, seg_id) if isinstance(seg_id, int) else None, d.get("timestamp")))
        n_definitions = len(cards)

        # 2. concept cards from the transcript
        usage = _Usage()
        batches = build_batches(topics, segments, self.settings.quiz_context_max_tokens)
        concept_target = max(0, limit - len(cards))
        counts = allocate(concept_target, [b.tokens for b in batches])
        terms = "\n".join(f"- {c.front}" for c in cards) or "(none)"
        for batch, count in zip(batches, counts):
            if count == 0:
                continue
            try:
                r = self.llm.complete(
                    task="flashcards",
                    prompt_id="flashcards",
                    schema=CardsOut,
                    variables={
                        "title": title,
                        "topics": "; ".join(batch.topic_titles),
                        "first_segment": batch.first_idx,
                        "last_segment": batch.last_idx,
                        "terms": terms,
                        "max_cards": count,
                        "transcript": numbered(batch.segments),
                    },
                    lecture_id=lecture_id,
                    user_id=user_id,
                )
            except LLMOutputInvalidError:
                dropped["invalid_json"] += 1
                continue
            usage.add(r)
            added = 0
            for item in r.data.cards:  # type: ignore[union-attr]
                front, back = item.front.strip(), item.back.strip()
                key = card_key(front)
                if not front or not back or not key:
                    dropped["empty"] += 1
                    continue
                if key in seen:
                    dropped["duplicate"] += 1
                    continue
                if not (batch.first_idx <= item.segment_id <= batch.last_idx) or item.segment_id not in by_idx:
                    dropped["segment_out_of_range"] += 1
                    continue
                if added >= count:
                    dropped["over_limit"] += 1
                    continue
                seen.add(key)
                added += 1
                seg = by_idx[item.segment_id]
                cards.append(DraftCard("concept", front[:MAX_FRONT], back[:MAX_BACK],
                                       topic_of(topics, seg.idx), seg.start_sec))

        meta = {
            "provider": usage.provider,
            "model": usage.model,
            "model_version": usage.model_version,
            "prompt_version": usage.prompts.get("flashcards"),
            "definition_cards": n_definitions,
            "concept_cards": len(cards) - n_definitions,
            "dropped": dict(dropped),
            "batches": len(batches),
            "llm_calls": usage.calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "llm_latency_ms": round(usage.latency_ms, 1),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        return DeckDraft(cards, meta)


@lru_cache
def get_flashcard_generator() -> FlashcardGenerator:
    from app.core.config import get_settings
    from app.services.llm.client import get_llm_client

    return FlashcardGenerator(get_settings(), get_llm_client())
