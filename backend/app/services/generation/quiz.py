"""Quiz generation (IMPLEMENTATION_PLAN §6 /generate-quiz, Phase 6).

Flow (all calls go through the logged LLM client):

    1. batches : the lecture's topics (Phase 5 notes) packed into transcript batches that fit
                 the free-tier limit (services/generation/context.py).
    2. slots   : the N requested questions are planned up front as numbered slots, each with
                 a type and difficulty (types round-robin; "mixed" cycles easy/medium/hard),
                 and spread over the batches in proportion to their length.
    3. ask     : one `quiz` request per batch for its slots.
    4. check   : every returned question is validated (below). Invalid or missing slots are
                 requested again, up to QUIZ_MAX_REGEN_ROUNDS extra times per batch.

Validation (an item failing any rule is discarded and its slot regenerated):
    - the slot number was requested and is still open, and the type matches the slot
    - question and explanation are non-empty; the question is not a duplicate
    - mcq: exactly 4 options, unique after normalising, and the answer is one of them
    - true_false: the answer is a boolean; short_answer: the answer is non-empty text
    - segment_id is a real segment inside the batch -> `source_start` = that segment's start,
      `topic` = the topic containing it (both from stored data, never from the model)

MCQ options are shuffled by the app so the correct letter is not always the model's favourite.
"""

import random
import re
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal

from fastapi import status
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import AppError
from app.services.generation.context import (
    Batch,
    TopicSpan,
    allocate,
    build_batches,
    numbered,
    topic_of,
)
from app.services.generation.summary import SegmentLike, _norm, _Usage
from app.services.llm.client import LLMClient
from app.services.llm.errors import LLMOutputInvalidError

QuestionType = Literal["mcq", "true_false", "short_answer"]
Difficulty = Literal["easy", "medium", "hard"]
QUESTION_TYPES: tuple[str, ...] = ("mcq", "true_false", "short_answer")
DIFFICULTIES: tuple[str, ...] = ("easy", "medium", "hard")
LETTERS = "ABCD"
AVOID_MAX = 20  # questions listed under "Already asked" (keeps the request small)

_OPTION_PREFIX = re.compile(r"^\s*(?:\(?[A-Da-d][\)\.:]|[A-Da-d]\s*[-–]\s)\s*")
_LETTER_ONLY = re.compile(r"\(?([A-Da-d])[\)\.:]?")


class QuizGenerationError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "QUIZ_GENERATION_FAILED"


# ---------------------------------------------------------------------------- LLM output schema


class QuestionItem(BaseModel):
    slot: int = Field(description="slot number from the user's list")
    type: str = Field(description="mcq | true_false | short_answer")
    question: str
    options: list[str] = Field(default_factory=list, description="mcq: exactly 4 option texts; else []")
    answer: bool | str = Field(description="mcq: exact text of the correct option; true_false: boolean; "
                                           "short_answer: model answer")
    key_points: list[str] = Field(default_factory=list, description="short_answer: points a correct answer contains")
    explanation: str
    segment_id: int = Field(description="id of the transcript segment that supports the answer")


class QuestionsOut(BaseModel):
    questions: list[QuestionItem]


# ---------------------------------------------------------------------------- plan + validation


@dataclass
class Slot:
    number: int  # 1-based within its batch
    type: str
    difficulty: str


@dataclass
class DraftQuestion:
    type: str
    difficulty: str
    topic: str | None
    question: str
    options: list[str] | None
    answer: Any  # "A".."D" | bool | reference text
    key_points: list[str] | None
    explanation: str
    source_start: float
    segment_id: int
    batch: int
    slot: int


def plan_slots(num_questions: int, types: Sequence[str], difficulty: str) -> list[tuple[str, str]]:
    """(type, difficulty) for every question, in order."""
    diffs = DIFFICULTIES if difficulty == "mixed" else (difficulty,)
    return [(types[i % len(types)], diffs[i % len(diffs)]) for i in range(num_questions)]


def clean_options(options: Sequence[str]) -> list[str]:
    """Strip "A) ", "B. " ... labels, but only when all options carry them in order A, B, C, D
    (so an option such as "D. melanogaster" is left alone)."""
    opts = [str(o).strip() for o in options]
    labels = [_OPTION_PREFIX.match(o) for o in opts]
    if len(opts) == 4 and all(labels) and [o.lstrip("( ")[0].upper() for o in opts] == list(LETTERS):
        return [_OPTION_PREFIX.sub("", o).strip() for o in opts]
    return opts


def _answer_letter(answer: str) -> str | None:
    m = _LETTER_ONLY.fullmatch(answer.strip())
    return m.group(1).upper() if m else None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def validate_item(
    item: QuestionItem,
    slot: Slot | None,
    batch: Batch,
    topics: Sequence[TopicSpan],
    by_idx: dict[int, SegmentLike],
    seen: set[str],
    rng: random.Random,
) -> tuple[DraftQuestion | None, str | None]:
    """Return (question, None) if valid, else (None, reason)."""
    if slot is None:
        return None, "unknown_or_filled_slot"
    if item.type != slot.type:
        return None, "wrong_type"
    question = item.question.strip()
    explanation = item.explanation.strip()
    if len(question) < 8:
        return None, "empty_question"
    if not explanation:
        return None, "empty_explanation"
    key = _norm(question)
    if key in seen:
        return None, "duplicate_question"
    if not (batch.first_idx <= item.segment_id <= batch.last_idx) or item.segment_id not in by_idx:
        return None, "segment_out_of_range"

    options: list[str] | None = None
    key_points: list[str] | None = None
    if slot.type == "mcq":
        labelled = [str(o).strip() for o in item.options]
        options = clean_options(labelled)
        if len(options) != 4 or any(not o for o in options):
            return None, "mcq_not_4_options"
        if len({_norm(o) for o in options}) != 4:
            return None, "mcq_duplicate_options"
        if isinstance(item.answer, bool) or not item.answer.strip():
            return None, "mcq_answer_not_in_options"
        letter = _answer_letter(item.answer)
        if letter is not None:
            correct = options[LETTERS.index(letter)]
        else:
            raw = item.answer.strip()
            if options != labelled:  # the options had labels, so the answer may too ("B) Paris")
                raw = _OPTION_PREFIX.sub("", raw).strip()
            matches = [o for o in options if _norm(o) == _norm(raw)]
            if len(matches) != 1:
                return None, "mcq_answer_not_in_options"
            correct = matches[0]
        rng.shuffle(options)
        answer: Any = LETTERS[options.index(correct)]
    elif slot.type == "true_false":
        answer = _as_bool(item.answer)
        if answer is None:
            return None, "true_false_answer_not_boolean"
    else:
        if isinstance(item.answer, bool) or not item.answer.strip():
            return None, "short_answer_empty_answer"
        answer = item.answer.strip()
        key_points = [p.strip() for p in item.key_points if p.strip()][:4] or [answer]

    seg = by_idx[item.segment_id]
    return (
        DraftQuestion(
            type=slot.type,
            difficulty=slot.difficulty,
            topic=topic_of(topics, item.segment_id) or (batch.topic_titles[0] if batch.topic_titles else None),
            question=question,
            options=options,
            answer=answer,
            key_points=key_points,
            explanation=explanation,
            source_start=seg.start_sec,
            segment_id=seg.idx,
            batch=batch.number,
            slot=slot.number,
        ),
        None,
    )


# ---------------------------------------------------------------------------- generator


@dataclass
class QuizDraft:
    questions: list[DraftQuestion]
    meta: dict[str, Any]
    model: str
    prompt_version: str


@dataclass
class _Stats:
    invalid: Counter = field(default_factory=Counter)
    regen_requests: int = 0


class QuizGenerator:
    def __init__(self, settings: Settings, llm: LLMClient, rng: random.Random | None = None) -> None:
        self.settings = settings
        self.llm = llm
        self.rng = rng or random.Random()

    def generate(
        self,
        *,
        lecture_id: uuid.UUID,
        user_id: uuid.UUID | None,
        title: str,
        topics: Sequence[TopicSpan],
        segments: Sequence[SegmentLike],
        num_questions: int,
        types: Sequence[str],
        difficulty: str,
    ) -> QuizDraft:
        by_idx = {s.idx: s for s in segments if s.text.strip()}
        batches = build_batches(topics, segments, self.settings.quiz_context_max_tokens)
        if not batches:
            raise QuizGenerationError("The selected topics have no transcript text to write questions from.")

        plan = plan_slots(num_questions, types, difficulty)
        counts = allocate(num_questions, [b.tokens for b in batches])
        usage, stats = _Usage(), _Stats()
        seen: set[str] = set()
        accepted: list[DraftQuestion] = []

        pos = 0
        for batch, count in zip(batches, counts):
            if count == 0:
                continue
            open_slots = {i + 1: Slot(i + 1, *plan[pos + i]) for i in range(count)}
            pos += count
            for round_no in range(1 + self.settings.quiz_max_regen_rounds):
                if not open_slots:
                    break
                if round_no:
                    stats.regen_requests += 1
                items = self._ask(batch, list(open_slots.values()), accepted, title, lecture_id, user_id, usage, stats)
                for item in items:
                    draft, reason = validate_item(
                        item, open_slots.get(item.slot), batch, topics, by_idx, seen, self.rng
                    )
                    if draft is None:
                        stats.invalid[reason] += 1
                        continue
                    seen.add(_norm(draft.question))
                    open_slots.pop(draft.slot)
                    accepted.append(draft)
            if open_slots:
                stats.invalid["slot_unfilled"] += len(open_slots)

        if not accepted:
            raise QuizGenerationError(
                "The model did not return any valid questions; please try again.",
                details={"invalid_reasons": dict(stats.invalid)},
            )
        accepted.sort(key=lambda q: (q.batch, q.slot))
        meta = {
            "provider": usage.provider,
            "model": usage.model,
            "model_version": usage.model_version,
            "prompt_version": usage.prompts.get("quiz"),
            "requested": num_questions,
            "generated": len(accepted),
            "invalid_items": sum(v for k, v in stats.invalid.items() if k != "slot_unfilled"),
            "invalid_reasons": dict(stats.invalid),
            "regeneration_requests": stats.regen_requests,
            "batches": len(batches),
            "llm_calls": usage.calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "llm_latency_ms": round(usage.latency_ms, 1),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        return QuizDraft(accepted, meta, usage.model or "", usage.prompts.get("quiz", ""))

    def _ask(
        self,
        batch: Batch,
        slots: list[Slot],
        accepted: list[DraftQuestion],
        title: str,
        lecture_id: uuid.UUID,
        user_id: uuid.UUID | None,
        usage: _Usage,
        stats: _Stats,
    ) -> list[QuestionItem]:
        avoid = [q.question for q in accepted][-AVOID_MAX:]
        try:
            r = self.llm.complete(
                task="quiz",
                prompt_id="quiz",
                schema=QuestionsOut,
                variables={
                    "title": title,
                    "topics": "; ".join(batch.topic_titles),
                    "first_segment": batch.first_idx,
                    "last_segment": batch.last_idx,
                    "slots": "\n".join(f"- slot {s.number}: {s.type}, {s.difficulty}" for s in slots),
                    "avoid": "\n".join(f"- {q}" for q in avoid) or "(none)",
                    "transcript": numbered(batch.segments),
                },
                lecture_id=lecture_id,
                user_id=user_id,
            )
        except LLMOutputInvalidError:
            stats.invalid["invalid_json"] += 1
            return []
        usage.add(r)
        return r.data.questions  # type: ignore[union-attr]


@lru_cache
def get_quiz_generator() -> QuizGenerator:
    from app.core.config import get_settings
    from app.services.llm.client import get_llm_client

    return QuizGenerator(get_settings(), get_llm_client())
