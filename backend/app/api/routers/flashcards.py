"""Flashcard routes: generate / list a lecture's deck, review a card (Leitner boxes).
HTTP only; the logic lives in services/flashcards.py (CLAUDE.md rule 6)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, FlashcardGen
from app.models.learning import Flashcard
from app.schemas.errors import error_responses
from app.schemas.flashcards import DeckOut, FlashcardOut, GenerateDeckRequest, ReviewRequest
from app.services import flashcards as card_service

router = APIRouter(tags=["flashcards"])


def _card_out(c: Flashcard) -> FlashcardOut:
    return FlashcardOut(
        id=c.id, kind=c.kind, front=c.front, back=c.back, topic=c.topic, timestamp=c.source_start,
        box=c.box, due_at=c.due_at, due=card_service.is_due(c), last_reviewed_at=c.last_reviewed_at,
    )


def _deck_out(lecture_id: uuid.UUID, cards: list[Flashcard], **extra) -> DeckOut:
    out = [_card_out(c) for c in cards]
    return DeckOut(lecture_id=lecture_id, total=len(out), due=sum(c.due for c in out), cards=out, **extra)


@router.post(
    "/lectures/{lecture_id}/flashcards",
    response_model=DeckOut,
    summary="Generate the lecture's flashcard deck (cached)",
    description=(
        "Definition cards come from the summary's definitions; concept cards are written by the LLM from the "
        "transcript. Duplicates are removed. Returns the stored deck unless `regenerate` is true, which "
        "replaces the deck and resets its review progress. Needs the summary/notes from POST /summarize."
    ),
    responses=error_responses(401, 404, 409, 429, 502, 503),
)
def generate_deck(
    lecture_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    generator: FlashcardGen,
    body: GenerateDeckRequest | None = None,
) -> DeckOut:
    cards, meta, cached = card_service.generate_deck(
        db, user, lecture_id, regenerate=bool(body and body.regenerate), generator=generator
    )
    return _deck_out(lecture_id, cards, cached=cached, meta=meta)


@router.get(
    "/lectures/{lecture_id}/flashcards",
    response_model=DeckOut,
    summary="The lecture's flashcards (optionally only those due now)",
    responses=error_responses(401, 404),
)
def list_deck(
    lecture_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    due: Annotated[bool, Query(description="true = only cards due for review now")] = False,
) -> DeckOut:
    return _deck_out(lecture_id, card_service.list_deck(db, user, lecture_id, due_only=due))


@router.post(
    "/flashcards/{card_id}/review",
    response_model=FlashcardOut,
    summary="Record knew / didn't know (moves the card between Leitner boxes)",
    responses=error_responses(401, 404, 422),
)
def review_card(card_id: uuid.UUID, body: ReviewRequest, user: CurrentUser, db: DbSession) -> FlashcardOut:
    return _card_out(card_service.review_card(db, user, card_id, knew=body.knew))
