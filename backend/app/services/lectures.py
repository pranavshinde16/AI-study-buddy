"""Lecture business logic: upload validation, owner-scoped reads, delete, transcript access.

Routers call these; no HTTP details here (CLAUDE.md rule 6). Every read is filtered by the
current user, so another user's lecture id gives 404, not 403 (we don't reveal it exists).
"""

import re
import uuid
from pathlib import PurePath
from typing import BinaryIO

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.models.lecture import Lecture, LectureStatus, TranscriptSegment
from app.models.user import User
from app.services.media import Media, UnsupportedMediaError
from app.services.storage import StorageService

# Extension -> content types browsers / curl send for it. application/octet-stream is also
# accepted for these extensions; ffprobe is the real check that the file is media.
ALLOWED_TYPES: dict[str, frozenset[str]] = {
    "mp3": frozenset({"audio/mpeg", "audio/mp3", "audio/mpeg3", "audio/x-mpeg-3"}),
    "wav": frozenset({"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"}),
    "mp4": frozenset({"video/mp4", "audio/mp4", "application/mp4"}),
    "m4a": frozenset({"audio/mp4", "audio/x-m4a", "audio/m4a", "audio/aac"}),
}
GENERIC_TYPES = frozenset({"application/octet-stream", ""})

# Stages after which the transcript exists.
TRANSCRIPT_READY = frozenset(
    {LectureStatus.TRANSCRIBED, LectureStatus.INDEXING, LectureStatus.GENERATING, LectureStatus.READY}
)
IN_PROGRESS = frozenset({LectureStatus.UPLOADED, LectureStatus.EXTRACTING_AUDIO, LectureStatus.TRANSCRIBING})


class LectureNotReadyError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "LECTURE_NOT_READY"


def check_file_type(filename: str | None, content_type: str | None) -> str:
    """Return the lowercase extension if the upload is an allowed type, else raise 415."""
    ext = PurePath(filename or "").suffix.lower().lstrip(".")
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ext not in ALLOWED_TYPES:
        raise UnsupportedMediaError(
            "Unsupported file type. Upload an MP3, WAV, MP4 or M4A file.",
            details={"allowed": sorted(ALLOWED_TYPES), "received_extension": ext or None},
        )
    if ctype not in ALLOWED_TYPES[ext] and ctype not in GENERIC_TYPES:
        raise UnsupportedMediaError(
            f"Content type '{ctype}' does not match a .{ext} file.",
            details={"allowed_content_types": sorted(ALLOWED_TYPES[ext])},
        )
    return ext


def default_title(filename: str | None) -> str:
    stem = PurePath(filename or "").stem
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return (stem or "Untitled lecture")[:300]


def create_lecture(
    db: Session,
    *,
    user: User,
    stream: BinaryIO,
    filename: str | None,
    content_type: str | None,
    title: str | None,
    storage: StorageService,
    media: Media,
    max_bytes: int,
) -> Lecture:
    """Validate type, save with a size limit, check it is real media, then insert the lecture row."""
    ext = check_file_type(filename, content_type)
    lecture_id = uuid.uuid4()
    path, size = storage.save_upload(stream, lecture_id, ext, max_bytes)
    try:
        if size == 0:
            raise UnsupportedMediaError("The uploaded file is empty")
        info = media.probe(path)
    except Exception:
        storage.delete_lecture(lecture_id)
        raise

    lecture = Lecture(
        id=lecture_id,
        user_id=user.id,
        title=(title or "").strip()[:300] or default_title(filename),
        original_filename=PurePath(filename or "").name[:500] or None,
        media_path=storage.relative(path),  # relative to STORAGE_DIR
        mime_type=(content_type or None),
        size_bytes=size,
        duration_sec=round(info.duration_sec, 3),
        status=LectureStatus.UPLOADED,
        progress=0,
    )
    db.add(lecture)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete_lecture(lecture_id)
        raise
    db.refresh(lecture)
    return lecture


def list_lectures(db: Session, user: User) -> list[Lecture]:
    return list(db.scalars(select(Lecture).where(Lecture.user_id == user.id).order_by(Lecture.created_at.desc())))


def get_lecture(db: Session, user: User, lecture_id: uuid.UUID) -> Lecture:
    lecture = db.get(Lecture, lecture_id)
    if lecture is None or lecture.user_id != user.id:
        raise NotFoundError("Lecture not found", code="LECTURE_NOT_FOUND")
    return lecture


def delete_lecture(db: Session, user: User, lecture_id: uuid.UUID, storage: StorageService) -> None:
    """Delete the row (segments, chunks, outputs, pipeline_runs cascade) and its files.
    A pipeline still running for it notices the row is gone and stops."""
    lecture = get_lecture(db, user, lecture_id)
    db.delete(lecture)
    db.commit()
    storage.delete_lecture(lecture_id)


def get_transcript(db: Session, user: User, lecture_id: uuid.UUID) -> tuple[Lecture, list[TranscriptSegment]]:
    lecture = get_lecture(db, user, lecture_id)
    if lecture.status not in TRANSCRIPT_READY:
        raise LectureNotReadyError(
            "The transcript is not ready yet",
            details={"status": lecture.status, "progress": lecture.progress},
        )
    segments = list(
        db.scalars(
            select(TranscriptSegment).where(TranscriptSegment.lecture_id == lecture.id).order_by(TranscriptSegment.idx)
        )
    )
    return lecture, segments


def safe_download_name(lecture: Lecture, ext: str) -> str:
    """ASCII file name for Content-Disposition."""
    base = re.sub(r"[^A-Za-z0-9 ._-]+", "", lecture.title).strip().replace(" ", "_") or "transcript"
    return f"{base[:80]}.{ext}"
