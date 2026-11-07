"""Summary & notes for a lecture: caching, status changes and the summarize/notes use cases.

Status flow after transcription (Phase 5):

    transcribed → generating → ready
                      └─ on failure → back to the previous status (transcribed + error message,
                                      or ready with the old outputs kept), never `failed`:
                                      the transcript is fine and generation can be retried.

Results are cached in `lecture_outputs` (kind=summary and kind=notes). A cached result is
returned instantly unless `regenerate=true`. Only one generation per lecture runs at a time
(an atomic status update "claims" the lecture).
"""

import uuid
from typing import Any

import structlog
from fastapi import status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ConflictError, NotFoundError
from app.models.lecture import Lecture, LectureOutput, LectureStatus, OutputKind, TranscriptSegment
from app.models.user import User
from app.services.generation.summary import GenerationResult, LectureGenerator
from app.services.lectures import TRANSCRIPT_READY, LectureNotReadyError, get_lecture

log = structlog.get_logger(__name__)

CLAIMABLE = (LectureStatus.TRANSCRIBED, LectureStatus.READY)
# Progress shown while generating (the transcription stages use 0-75).
P_GEN_START, P_GEN_END = 75, 99


class GenerationInProgressError(ConflictError):
    code = "GENERATION_IN_PROGRESS"


class NotesNotGeneratedError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "NOTES_NOT_GENERATED"


class _Gone(Exception):
    """The lecture was deleted during generation."""


# ---------------------------------------------------------------------------- cache


def load_outputs(db: Session, lecture_id: uuid.UUID) -> dict[str, LectureOutput]:
    rows = db.scalars(select(LectureOutput).where(LectureOutput.lecture_id == lecture_id))
    return {r.kind: r for r in rows}


def _save_outputs(db: Session, lecture_id: uuid.UUID, result: GenerationResult) -> None:
    db.execute(
        delete(LectureOutput).where(
            LectureOutput.lecture_id == lecture_id,
            LectureOutput.kind.in_([OutputKind.SUMMARY, OutputKind.NOTES]),
        )
    )
    db.add_all(
        [
            LectureOutput(lecture_id=lecture_id, kind=OutputKind.SUMMARY, content_json=result.summary,
                          prompt_version=result.summary_prompt, model=result.model),
            LectureOutput(lecture_id=lecture_id, kind=OutputKind.NOTES, content_json=result.notes,
                          prompt_version=result.notes_prompt, model=result.model),
        ]
    )


# ---------------------------------------------------------------------------- status helpers


def _set(db: Session, lecture_id: uuid.UUID, **values: Any) -> None:
    if db.execute(update(Lecture).where(Lecture.id == lecture_id).values(**values)).rowcount == 0:
        raise _Gone()
    db.commit()


def _claim(db: Session, lecture_id: uuid.UUID) -> str | None:
    """Atomically move transcribed/ready -> generating. Returns the previous status, or None if
    another generation is running (or the lecture isn't transcribed)."""
    for prev in CLAIMABLE:
        res = db.execute(
            update(Lecture)
            .where(Lecture.id == lecture_id, Lecture.status == prev)
            .values(status=LectureStatus.GENERATING, progress=P_GEN_START, stage_detail="Preparing summary", error=None)
        )
        if res.rowcount:
            db.commit()
            return prev
    db.rollback()
    return None


def generate_and_store(
    db: Session,
    lecture_id: uuid.UUID,
    generator: LectureGenerator,
    *,
    raise_errors: bool,
) -> bool:
    """Generate summary + notes and cache them; returns True on success.

    raise_errors=False is used by the background pipeline (failures are recorded on the lecture);
    raise_errors=True is used by POST /summarize (the error is returned to the caller)."""
    prev = _claim(db, lecture_id)
    if prev is None:
        if raise_errors:
            raise GenerationInProgressError("Summary generation is already running for this lecture")
        return False

    try:
        lecture = db.get(Lecture, lecture_id, populate_existing=True)
        if lecture is None:
            raise _Gone()
        segments = list(
            db.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.lecture_id == lecture_id)
                .order_by(TranscriptSegment.idx)
            )
        )

        def progress(detail: str, fraction: float) -> None:
            pct = P_GEN_START + int((P_GEN_END - P_GEN_START) * min(max(fraction, 0.0), 1.0))
            _set(db, lecture_id, progress=pct, stage_detail=f"Generating summary: {detail}")

        result = generator.generate(
            lecture_id=lecture_id, user_id=lecture.user_id, title=lecture.title, segments=segments, on_progress=progress
        )
        _save_outputs(db, lecture_id, result)
        _set(db, lecture_id, status=LectureStatus.READY, progress=100, error=None,
             stage_detail=f"Summary and {len(result.notes['topics'])} topic notes ready")
        log.info("summary_generated", lecture_id=str(lecture_id), mode=result.summary["meta"]["mode"],
                 llm_calls=result.summary["meta"]["llm_calls"])
        return True
    except (_Gone, IntegrityError):
        db.rollback()
        log.info("summary_stopped_lecture_deleted", lecture_id=str(lecture_id))
        if raise_errors:
            raise NotFoundError("Lecture not found", code="LECTURE_NOT_FOUND") from None
        return False
    except Exception as exc:
        db.rollback()
        message = exc.message if isinstance(exc, AppError) else f"unexpected error ({type(exc).__name__})"
        if not isinstance(exc, AppError):
            log.exception("summary_crashed", lecture_id=str(lecture_id), error_type=type(exc).__name__)
        _restore(db, lecture_id, prev, message)
        if raise_errors:
            raise
        return False


def _restore(db: Session, lecture_id: uuid.UUID, prev: str, message: str) -> None:
    """Undo the claim after a failure. The transcript (and any older outputs) stay usable."""
    if prev == LectureStatus.READY:
        values = {"status": prev, "progress": 100, "error": None,
                  "stage_detail": f"Regeneration failed ({message[:200]}); the previous summary is kept"}
    else:
        values = {
            "status": prev,
            "progress": 100,
            "error": f"Summary generation failed: {message}"[:2000],
            "stage_detail": "Transcript ready; retry with POST /api/lectures/{id}/summarize".replace("{id}", str(lecture_id)),
        }
    try:
        _set(db, lecture_id, **values)
    except _Gone:
        db.rollback()
    log.warning("summary_failed", lecture_id=str(lecture_id), error_message=message)


def mark_generation_interrupted(db: Session) -> int:
    """Startup sweep: a restart during `generating` returns the lecture to `transcribed`."""
    res = db.execute(
        update(Lecture)
        .where(Lecture.status == LectureStatus.GENERATING)
        .values(status=LectureStatus.TRANSCRIBED, progress=100,
                error="Summary generation was interrupted by a server restart; retry with POST /summarize.",
                stage_detail="Transcript ready")
    )
    db.commit()
    return res.rowcount or 0


# ---------------------------------------------------------------------------- use cases (routers call these)


def summarize(
    db: Session,
    user: User,
    lecture_id: uuid.UUID,
    *,
    regenerate: bool,
    generator: LectureGenerator,
) -> tuple[dict[str, LectureOutput], bool]:
    """Return (outputs by kind, cached?). Generates synchronously if needed."""
    lecture = get_lecture(db, user, lecture_id)
    if lecture.status not in TRANSCRIPT_READY:
        raise LectureNotReadyError(
            "The transcript is not ready yet", details={"status": lecture.status, "progress": lecture.progress}
        )
    outputs = load_outputs(db, lecture_id)
    if not regenerate and OutputKind.SUMMARY in outputs and OutputKind.NOTES in outputs:
        return outputs, True
    if lecture.status == LectureStatus.GENERATING:
        raise GenerationInProgressError(
            "Summary generation is already running for this lecture; poll /status and try again when it is ready"
        )
    generate_and_store(db, lecture_id, generator, raise_errors=True)
    db.expire_all()
    return load_outputs(db, lecture_id), False


def get_notes(db: Session, user: User, lecture_id: uuid.UUID) -> LectureOutput:
    lecture = get_lecture(db, user, lecture_id)
    notes = load_outputs(db, lecture_id).get(OutputKind.NOTES)
    if notes is not None:
        return notes
    if lecture.status == LectureStatus.GENERATING:
        raise GenerationInProgressError("Notes are being generated; poll /status")
    raise NotesNotGeneratedError(
        "Notes have not been generated yet. Call POST /api/lectures/{id}/summarize.".replace("{id}", str(lecture_id)),
        details={"status": lecture.status},
    )
