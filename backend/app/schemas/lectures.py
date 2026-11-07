"""Request/response shapes for /api/lectures (IMPLEMENTATION_PLAN §6).

Segments are stored as start_sec/end_sec and exposed as `start` / `end` (seconds).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UploadResponse(BaseModel):
    lecture_id: uuid.UUID
    title: str
    status: str
    status_url: str


class LectureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str | None
    status: str
    progress: int
    stage_detail: str | None
    error: str | None
    duration_sec: float | None
    language: str | None
    size_bytes: int | None
    created_at: datetime
    updated_at: datetime


class LectureStatusOut(BaseModel):
    status: str = Field(description="uploaded → extracting_audio → transcribing → transcribed | failed")
    progress: int = Field(ge=0, le=100)
    stage_detail: str | None
    error: str | None


class SegmentOut(BaseModel):
    id: int = Field(description="Position of the segment in the transcript (0-based)")
    start: float = Field(description="Seconds from the start of the lecture")
    end: float
    text: str


class TranscriptOut(BaseModel):
    lecture_id: uuid.UUID
    duration_sec: float | None
    language: str | None
    segments: list[SegmentOut]
