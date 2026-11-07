"""Flashcard use cases: generate a deck (cached), list it, and review a card (Leitner boxes).

Leitner system with 5 boxes. A new card starts in box 1 and is due now.

    knew it        -> move up one box (max 5), due again after the new box's interval
    didn't know it -> back to box 1, due again now (so it comes back in the same session)

    box      : 1     2    3    4    5
    interval : now   1d   3d   7d   14d

The deck is generated once per user and lecture; POST /flashcards returns the stored deck
unless `regenerate=true`, which replaces it (and its review progress) with a new one.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.learning import Flashcard
from app.models.lecture import OutputKind
from app.models.user import User
from app.services.generation.flashcards import FlashcardGenerator
from app.services.lectures import get_lecture
from app.services.quizzes import lecture_context

MAX_BOX = 5
BOX_INTERVAL_DAYS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 14}


def now_utc() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes (stored as UTC); PostgreSQL returns aware ones."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def deck_of(db: Session, user_id: uuid.UUID, lecture_id: uuid.UUID, *, due_only: bool = False,
            now: datetime | None = None) -> list[Flashcard]:
    q = select(Flashcard).where(Flashcard.user_id == user_id, Flashcard.lecture_id == lecture_id)
    cards = list(db.scalars(q.order_by(Flashcard.created_at, Flashcard.id)))
    cards.sort(key=lambda c: (c.kind != "definition", c.source_start if c.source_start is not None else 1e12))
    if due_only:
        t = now or now_utc()
        cards = [c for c in cards if _aware(c.due_at) <= t]
    return cards


def is_due(card: Flashcard, now: datetime | None = None) -> bool:
    return _aware(card.due_at) <= (now or now_utc())


def generate_deck(
    db: Session,
    user: User,
    lecture_id: uuid.UUID,
    *,
    regenerate: bool,
    generator: FlashcardGenerator,
) -> tuple[list[Flashcard], dict[str, Any] | None, bool]:
    """Return (cards, generation meta or None if cached, cached?)."""
    lecture, topics, segments, outputs = lecture_context(db, user, lecture_id)
    existing = deck_of(db, user.id, lecture_id)
    if existing and not regenerate:
        return existing, None, True

    definitions = (outputs.get(OutputKind.SUMMARY) or {}).get("definitions", [])
    draft = generator.generate(
        lecture_id=lecture.id, user_id=user.id, title=lecture.title,
        topics=topics, segments=segments, definitions=definitions,
    )
    now = now_utc()
    db.execute(delete(Flashcard).where(Flashcard.user_id == user.id, Flashcard.lecture_id == lecture_id))
    db.add_all(
        Flashcard(lecture_id=lecture_id, user_id=user.id, front=c.front, back=c.back, topic=c.topic,
                  kind=c.kind, source_start=c.source_start, box=1, due_at=now)
        for c in draft.cards
    )
    try:
        db.commit()
    except IntegrityError:  # the lecture was deleted meanwhile
        db.rollback()
        raise NotFoundError("Lecture not found", code="LECTURE_NOT_FOUND") from None
    return deck_of(db, user.id, lecture_id), draft.meta, False


def list_deck(db: Session, user: User, lecture_id: uuid.UUID, *, due_only: bool) -> list[Flashcard]:
    get_lecture(db, user, lecture_id)
    return deck_of(db, user.id, lecture_id, due_only=due_only)


def review_card(db: Session, user: User, card_id: uuid.UUID, *, knew: bool, now: datetime | None = None) -> Flashcard:
    card = db.scalar(select(Flashcard).where(Flashcard.id == card_id, Flashcard.user_id == user.id))
    if card is None:
        raise NotFoundError("Flashcard not found", code="FLASHCARD_NOT_FOUND")
    t = now or now_utc()
    card.box = min(MAX_BOX, card.box + 1) if knew else 1
    card.due_at = t + timedelta(days=BOX_INTERVAL_DAYS[card.box])
    card.last_reviewed_at = t
    db.commit()
    db.refresh(card)
    return card
