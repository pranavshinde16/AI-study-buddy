"""Background lecture pipeline (IMPLEMENTATION_PLAN §5.3), started by the upload endpoint.

Phase 4 stages:
    uploaded → extracting_audio → transcribing → transcribed   (or → failed)
Later phases continue from `transcribed` to indexing → generating → ready.

It runs in FastAPI's BackgroundTasks thread pool with its own DB session, commits after every
status change so `GET /lectures/{id}/status` shows live progress, and writes one
`pipeline_runs` row per stage (duration + audio seconds → real-time factor, metric M1).
"""

import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import Settings
from app.core.errors import AppError
from app.models.lecture import Lecture, LectureStatus, TranscriptSegment
from app.models.llmops import PipelineRun
from app.services.asr.client import ASRClient
from app.services.asr.providers import ASRSegment
from app.services.lectures import IN_PROGRESS
from app.services.media import AudioChunk, Media
from app.services.storage import StorageService

log = structlog.get_logger(__name__)

# Progress % shown while each stage runs.
P_EXTRACT, P_TRANSCRIBE_START, P_TRANSCRIBE_END = 5, 10, 95


class LectureGone(Exception):
    """The lecture was deleted while the pipeline was running."""


def merge_segments(chunk_results: list[tuple[AudioChunk, list[ASRSegment]]]) -> list[tuple[float, float, str]]:
    """Shift each chunk's segments by the chunk's offset and join them into one timeline.

    Times are clamped to the chunk's own span so pieces never overlap and the timeline stays
    continuous and increasing. Empty segments are dropped. Times come only from ASR (rule 3).
    """
    merged: list[tuple[float, float, str]] = []
    for chunk, segments in chunk_results:
        lo, hi = chunk.offset_sec, chunk.offset_sec + chunk.duration_sec
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            start = min(max(lo, chunk.offset_sec + seg.start), hi)
            end = min(max(start, chunk.offset_sec + seg.end), hi)
            if merged and start < merged[-1][1]:
                start = merged[-1][1]
                end = max(end, start)
            merged.append((round(start, 3), round(end, 3), text))
    return merged


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session] | Callable[[], Session],
        storage: StorageService,
        media: Media,
        asr: ASRClient,
    ) -> None:
        self.settings = settings
        self._session_factory = session_factory
        self.storage = storage
        self.media = media
        self.asr = asr

    # ------------------------------------------------------------------ entry point

    def run(self, lecture_id: uuid.UUID) -> None:
        log.info("pipeline_start", lecture_id=str(lecture_id))
        with self._session_factory() as db:
            try:
                self._run(db, lecture_id)
                log.info("pipeline_done", lecture_id=str(lecture_id))
            except (LectureGone, StaleDataError):
                db.rollback()
                log.info("pipeline_stopped_lecture_deleted", lecture_id=str(lecture_id))
            except AppError as exc:
                db.rollback()
                self._fail(db, lecture_id, exc.message)
            except Exception as exc:  # noqa: BLE001 - background task: record, never raise
                db.rollback()
                log.exception("pipeline_crashed", lecture_id=str(lecture_id), error_type=type(exc).__name__)
                self._fail(db, lecture_id, f"Processing failed unexpectedly ({type(exc).__name__}).")
            finally:
                shutil.rmtree(self.storage.audio_dir(lecture_id), ignore_errors=True)

    # ------------------------------------------------------------------ stages

    def _run(self, db: Session, lecture_id: uuid.UUID) -> None:
        lecture = self._lecture(db, lecture_id)
        if not lecture.media_path:
            raise AppError("The lecture has no stored media file", code="MEDIA_MISSING")
        source = self.storage.resolve(lecture.media_path)
        user_id = lecture.user_id
        audio_sec = lecture.duration_sec

        # 1. extracting_audio
        self._set(db, lecture, LectureStatus.EXTRACTING_AUDIO, P_EXTRACT, "Converting to 16 kHz mono audio")
        with self._stage(db, lecture_id, LectureStatus.EXTRACTING_AUDIO, audio_sec):
            chunks = self.media.extract_chunks(
                source,
                self.storage.audio_dir(lecture_id),
                self.settings.asr_chunk_sec,
                int(self.settings.asr_max_chunk_mb * 1024 * 1024),
            )
        log.info("audio_extracted", lecture_id=str(lecture_id), chunks=len(chunks))

        # 2. transcribing
        lecture = self._lecture(db, lecture_id)
        self._set(db, lecture, LectureStatus.TRANSCRIBING, P_TRANSCRIBE_START, f"chunk 1 of {len(chunks)}")
        results: list[tuple[AudioChunk, list[ASRSegment]]] = []
        language: str | None = None
        with self._stage(db, lecture_id, LectureStatus.TRANSCRIBING, audio_sec):
            for chunk in chunks:
                lecture = self._lecture(db, lecture_id)
                span = P_TRANSCRIBE_END - P_TRANSCRIBE_START
                progress = P_TRANSCRIBE_START + int(span * chunk.index / len(chunks))
                self._set(db, lecture, LectureStatus.TRANSCRIBING, progress, f"chunk {chunk.index + 1} of {len(chunks)}")
                res = self.asr.transcribe_chunk(
                    chunk.path, audio_sec=chunk.duration_sec, lecture_id=lecture_id, user_id=user_id
                )
                language = language or res.language
                results.append((chunk, res.segments))

        # 3. save the merged transcript
        merged = merge_segments(results)
        lecture = self._lecture(db, lecture_id)
        db.execute(delete(TranscriptSegment).where(TranscriptSegment.lecture_id == lecture_id))
        db.add_all(
            TranscriptSegment(lecture_id=lecture_id, idx=i, start_sec=s, end_sec=e, text=t)
            for i, (s, e, t) in enumerate(merged)
        )
        lecture.language = (language or "")[:16] or None
        self._set(db, lecture, LectureStatus.TRANSCRIBED, 100, f"{len(merged)} segments; ready for indexing")

    # ------------------------------------------------------------------ helpers

    def _lecture(self, db: Session, lecture_id: uuid.UUID) -> Lecture:
        lecture = db.get(Lecture, lecture_id, populate_existing=True)
        if lecture is None:
            raise LectureGone()
        return lecture

    @staticmethod
    def _set(db: Session, lecture: Lecture, status: str, progress: int, detail: str | None) -> None:
        lecture.status = status
        lecture.progress = progress
        lecture.stage_detail = detail
        lecture.error = None
        db.commit()

    def _stage(self, db: Session, lecture_id: uuid.UUID, stage: str, audio_sec: float | None) -> "_StageTimer":
        return _StageTimer(self._session_factory, lecture_id, stage, audio_sec)

    def _fail(self, db: Session, lecture_id: uuid.UUID, message: str) -> None:
        log.warning("pipeline_failed", lecture_id=str(lecture_id), error_message=message)
        try:
            db.execute(
                update(Lecture)
                .where(Lecture.id == lecture_id)
                .values(status=LectureStatus.FAILED, error=message[:2000], stage_detail=None)
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.warning("pipeline_fail_update_failed", error_type=type(exc).__name__)


class _StageTimer:
    """Writes a `pipeline_runs` row: status=running at start, ok/failed with duration at the end.
    Uses its own session so the timing row is saved even if the main transaction rolls back."""

    def __init__(self, session_factory, lecture_id: uuid.UUID, stage: str, audio_sec: float | None) -> None:
        self._sf = session_factory
        self.lecture_id = lecture_id
        self.stage = stage
        self.audio_sec = audio_sec
        self.run_id: uuid.UUID | None = None
        self._t0 = datetime.now(UTC)

    def __enter__(self) -> "_StageTimer":
        self._t0 = datetime.now(UTC)
        try:
            with self._sf() as s:
                row = PipelineRun(
                    lecture_id=self.lecture_id, stage=self.stage, started_at=self._t0,
                    audio_sec=self.audio_sec, status="running",
                )
                s.add(row)
                s.commit()
                self.run_id = row.id
        except Exception as exc:  # noqa: BLE001 - e.g. lecture deleted; timing is best-effort
            log.warning("pipeline_run_log_failed", stage=self.stage, error_type=type(exc).__name__)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.run_id is None:
            return
        ended = datetime.now(UTC)
        message = getattr(exc, "message", None) or (str(exc) if exc else None)
        try:
            with self._sf() as s:
                s.execute(
                    update(PipelineRun)
                    .where(PipelineRun.id == self.run_id)
                    .values(
                        ended_at=ended,
                        duration_ms=round((ended - self._t0).total_seconds() * 1000, 2),
                        status="ok" if exc_type is None else "failed",
                        error_message=message[:2000] if message else None,
                    )
                )
                s.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("pipeline_run_log_failed", stage=self.stage, error_type=type(e).__name__)


def mark_interrupted(session_factory: sessionmaker[Session] | Callable[[], Session]) -> int:
    """On startup: lectures left mid-pipeline by a server restart can't resume, so mark them failed."""
    with session_factory() as db:
        ids = list(db.scalars(select(Lecture.id).where(Lecture.status.in_([str(s) for s in IN_PROGRESS]))))
        if ids:
            db.execute(
                update(Lecture)
                .where(Lecture.id.in_(ids))
                .values(
                    status=LectureStatus.FAILED,
                    error="Processing was interrupted by a server restart. Delete the lecture and upload it again.",
                    stage_detail=None,
                )
            )
            db.commit()
        return len(ids)


@lru_cache
def get_pipeline() -> Pipeline:
    """Default pipeline wired to the real DB, storage, ffmpeg and ASR client (tests override it)."""
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.services.asr.client import get_asr_client
    from app.services.media import media_from_settings
    from app.services.storage import storage_from_settings

    s = get_settings()
    return Pipeline(s, get_session_factory(), storage_from_settings(s), media_from_settings(s), get_asr_client())
