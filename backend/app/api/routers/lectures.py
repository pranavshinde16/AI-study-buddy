"""/api/lectures: upload, list, status, delete, transcript and transcript download.
HTTP only; the logic lives in services/lectures.py and workers/pipeline.py (CLAUDE.md rule 6)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Response, UploadFile, status

from app.api.deps import AppSettings, CurrentUser, DbSession, LecturePipeline, MediaTools, Storage
from app.schemas.errors import error_responses
from app.schemas.lectures import LectureOut, LectureStatusOut, SegmentOut, TranscriptOut, UploadResponse
from app.services import lectures as lecture_service
from app.services.transcript_format import MEDIA_TYPES, TranscriptFormat, render

router = APIRouter(prefix="/lectures", tags=["lectures"])


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a lecture (MP3, WAV, MP4 or M4A) and start transcription",
    responses=error_responses(401, 413, 415, 422, 503),
)
def upload_lecture(
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    storage: Storage,
    media: MediaTools,
    pipeline: LecturePipeline,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="Lecture recording")],
    title: Annotated[str | None, Form(max_length=300)] = None,
) -> UploadResponse:
    lecture = lecture_service.create_lecture(
        db,
        user=user,
        stream=file.file,
        filename=file.filename,
        content_type=file.content_type,
        title=title,
        storage=storage,
        media=media,
        max_bytes=settings.max_upload_mb * 1024 * 1024,
    )
    background.add_task(pipeline.run, lecture.id)
    return UploadResponse(
        lecture_id=lecture.id,
        title=lecture.title,
        status=lecture.status,
        status_url=f"/api/lectures/{lecture.id}/status",
    )


@router.get("", response_model=list[LectureOut], summary="List your lectures", responses=error_responses(401))
def list_lectures(user: CurrentUser, db: DbSession) -> list[LectureOut]:
    return [LectureOut.model_validate(lec) for lec in lecture_service.list_lectures(db, user)]


@router.get("/{lecture_id}", response_model=LectureOut, summary="Lecture metadata", responses=error_responses(401, 404))
def get_lecture(lecture_id: uuid.UUID, user: CurrentUser, db: DbSession) -> LectureOut:
    return LectureOut.model_validate(lecture_service.get_lecture(db, user, lecture_id))


@router.get(
    "/{lecture_id}/status",
    response_model=LectureStatusOut,
    summary="Pipeline stage and progress % (poll every few seconds)",
    responses=error_responses(401, 404),
)
def get_status(lecture_id: uuid.UUID, user: CurrentUser, db: DbSession) -> LectureStatusOut:
    lec = lecture_service.get_lecture(db, user, lecture_id)
    return LectureStatusOut(status=lec.status, progress=lec.progress, stage_detail=lec.stage_detail, error=lec.error)


@router.delete(
    "/{lecture_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a lecture, its transcript and its files",
    responses=error_responses(401, 404),
)
def delete_lecture(lecture_id: uuid.UUID, user: CurrentUser, db: DbSession, storage: Storage) -> Response:
    lecture_service.delete_lecture(db, user, lecture_id, storage)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{lecture_id}/transcript",
    response_model=TranscriptOut,
    summary="Timestamped transcript segments",
    responses=error_responses(401, 404, 409),
)
def get_transcript(lecture_id: uuid.UUID, user: CurrentUser, db: DbSession) -> TranscriptOut:
    lecture, segments = lecture_service.get_transcript(db, user, lecture_id)
    return TranscriptOut(
        lecture_id=lecture.id,
        duration_sec=lecture.duration_sec,
        language=lecture.language,
        segments=[SegmentOut(id=s.idx, start=s.start_sec, end=s.end_sec, text=s.text) for s in segments],
    )


@router.get(
    "/{lecture_id}/transcript/download",
    summary="Download the transcript as txt, srt or vtt",
    response_class=Response,
    responses={200: {"content": {v.split(";")[0]: {} for v in MEDIA_TYPES.values()}}, **error_responses(401, 404, 409, 422)},
)
def download_transcript(
    lecture_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    format: Annotated[TranscriptFormat, Query(description="txt | srt | vtt")] = "txt",  # noqa: A002
) -> Response:
    lecture, segments = lecture_service.get_transcript(db, user, lecture_id)
    filename = lecture_service.safe_download_name(lecture, format)
    return Response(
        content=render(segments, format),
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
