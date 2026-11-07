"""Saving `llm_calls` rows (shared by the LLM and ASR clients).

Logging must never break a user's request. If the lecture or user a call belongs to was
deleted while the request was running, the foreign key fails; the row is then saved without
those links, so the real call is still counted in the metrics.
"""

import uuid
from collections.abc import Callable

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.llmops import LLMCall

log = structlog.get_logger(__name__)


def _unlinked(row: LLMCall) -> LLMCall:
    skip = {"id", "lecture_id", "user_id"}
    cols = {c.key: getattr(row, c.key) for c in LLMCall.__table__.columns if c.key not in skip}
    return LLMCall(**{k: v for k, v in cols.items() if v is not None})  # unset -> DB defaults (e.g. ts)


def save_call(session_factory: sessionmaker[Session] | Callable[[], Session], row: LLMCall) -> uuid.UUID | None:
    """Insert the row; returns its id, or None if it could not be saved."""
    for candidate in (row, _unlinked(row)):
        try:
            with session_factory() as session:
                session.add(candidate)
                session.commit()
                return candidate.id
        except IntegrityError:
            continue  # linked lecture/user is gone: retry unlinked
        except Exception as exc:  # noqa: BLE001
            log.warning("llm_call_log_failed", task=row.task, error_type=type(exc).__name__)
            return None
    log.warning("llm_call_log_failed", task=row.task, error_type="IntegrityError")
    return None
