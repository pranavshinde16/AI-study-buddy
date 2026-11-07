"""Background pipeline: stages, merged timestamps across chunks, pipeline_runs timings, failures."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.lecture import Lecture, LectureStatus, TranscriptSegment
from app.models.llmops import LLMCall, PipelineRun
from app.models.user import User
from app.services.asr.providers import ASRSegment
from app.services.media import AudioChunk
from app.workers.pipeline import mark_interrupted, merge_segments
from tests.fakes import rate_limited
from tests.fixtures.audio import make_tone, needs_ffmpeg


def _chunk(i: int, offset: float, dur: float) -> AudioChunk:
    return AudioChunk(i, Path(f"chunk_{i:03d}.flac"), offset, dur, 1)


def test_merge_shifts_offsets_and_keeps_timeline_increasing():
    merged = merge_segments(
        [
            (_chunk(0, 0.0, 10.0), [ASRSegment(0.0, 4.0, "a"), ASRSegment(4.0, 10.4, "b"), ASRSegment(9.0, 9.5, "  ")]),
            (_chunk(1, 10.0, 10.0), [ASRSegment(-0.2, 3.0, "c"), ASRSegment(3.0, 9.8, "d")]),
        ]
    )
    assert merged == [
        (0.0, 4.0, "a"),
        (4.0, 10.0, "b"),  # clamped to the chunk's end (Whisper overshoot)
        (10.0, 13.0, "c"),  # shifted by the offset; negative start clamped to the chunk start
        (13.0, 19.8, "d"),
    ]
    for (s1, e1, _), (s2, _e2, _t) in zip(merged, merged[1:]):
        assert e1 <= s2


def _make_lecture(db, storage, tmp_path, seconds: float) -> Lecture:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    db.add(user)
    db.commit()
    lecture_id = uuid.uuid4()
    src = make_tone(tmp_path / "src.mp3", seconds)
    with src.open("rb") as f:
        path, size = storage.save_upload(f, lecture_id, "mp3", 10 * 1024 * 1024)
    lec = Lecture(id=lecture_id, user_id=user.id, title="Tone", media_path=storage.relative(path),
                  size_bytes=size, duration_sec=seconds)
    db.add(lec)
    db.commit()
    return lec


@needs_ffmpeg
def test_pipeline_end_to_end_with_fake_asr(pipeline, fake_asr, storage, db, tmp_path):
    lec = _make_lecture(db, storage, tmp_path, 25)  # settings.asr_chunk_sec = 10 -> 3 chunks
    seen_status: list[str] = []

    def spy(_path):
        with pipeline._session_factory() as s:
            seen_status.append(s.get(Lecture, lec.id).status)

    fake_asr.on_call = spy
    pipeline.run(lec.id)

    db.expire_all()
    lec = db.get(Lecture, lec.id)
    assert (lec.status, lec.progress, lec.error, lec.language) == (LectureStatus.TRANSCRIBED, 100, None, "en")
    assert seen_status == ["transcribing"] * 3

    segs = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.lecture_id == lec.id)
                           .order_by(TranscriptSegment.idx)))
    assert [(s.idx, s.start_sec, s.end_sec, s.text) for s in segs] == [
        (0, 0.0, 1.0, "part 1 hello"), (1, 1.0, 1.9, "part 1 world"),
        (2, 10.0, 11.0, "part 2 hello"), (3, 11.0, 11.9, "part 2 world"),
        (4, 20.0, 21.0, "part 3 hello"), (5, 21.0, 21.9, "part 3 world"),
    ]

    runs = {r.stage: r for r in db.scalars(select(PipelineRun).where(PipelineRun.lecture_id == lec.id))}
    assert set(runs) == {"extracting_audio", "transcribing", "indexing"}
    assert all(r.status == "ok" and r.duration_ms is not None and r.audio_sec == 25 for r in runs.values())

    # Phase 7: the transcript was indexed (one short chunk here) and the vector store has it
    from app.models.lecture import Chunk

    chunks = list(db.scalars(select(Chunk).where(Chunk.lecture_id == lec.id)))
    assert len(chunks) == 1 and chunks[0].start_sec == 0.0 and chunks[0].end_sec == 21.9
    assert pipeline.indexer.store.count(lec.id) == 1
    assert "1 chunks indexed" in lec.stage_detail

    calls = list(db.scalars(select(LLMCall).where(LLMCall.task == "asr")))
    assert len(calls) == 3 and all(c.lecture_id == lec.id and c.status == "ok" for c in calls)
    assert not storage.audio_dir(lec.id).exists()  # temporary chunks cleaned up


@needs_ffmpeg
def test_pipeline_records_failure_without_paid_fallback(pipeline, fake_asr, storage, db, tmp_path):
    lec = _make_lecture(db, storage, tmp_path, 5)
    fake_asr.script = [rate_limited()] * 4  # 1 try + 3 retries

    pipeline.run(lec.id)

    db.expire_all()
    lec = db.get(Lecture, lec.id)
    assert lec.status == LectureStatus.FAILED
    assert "no paid fallback" in lec.error
    run = db.scalar(select(PipelineRun).where(PipelineRun.lecture_id == lec.id, PipelineRun.stage == "transcribing"))
    assert run.status == "failed" and run.error_message
    assert db.scalar(select(TranscriptSegment).where(TranscriptSegment.lecture_id == lec.id)) is None


@needs_ffmpeg
def test_pipeline_stops_quietly_if_lecture_deleted(pipeline, fake_asr, storage, db, tmp_path):
    lecture_id = _make_lecture(db, storage, tmp_path, 5).id

    def delete_it(_path):
        with pipeline._session_factory() as s:
            s.delete(s.get(Lecture, lecture_id))
            s.commit()

    fake_asr.on_call = delete_it
    pipeline.run(lecture_id)  # must not raise

    db.expire_all()
    assert db.get(Lecture, lecture_id) is None
    # The real ASR request is still counted in llm_calls (unlinked from the deleted lecture).
    [call] = db.scalars(select(LLMCall).where(LLMCall.task == "asr"))
    assert call.lecture_id is None and call.status == "ok" and call.ts is not None


def test_pipeline_fails_cleanly_on_unreadable_media(pipeline, storage, db, tmp_path):
    user = User(email="x@example.com", password_hash="x")
    db.add(user)
    db.commit()
    lec = Lecture(user_id=user.id, title="Broken", media_path="uploads/missing/original.mp3")
    db.add(lec)
    db.commit()

    pipeline.run(lec.id)

    db.expire_all()
    lec = db.get(Lecture, lec.id)
    assert lec.status == LectureStatus.FAILED and lec.error


@pytest.mark.parametrize("stuck", ["uploaded", "extracting_audio", "transcribing"])
def test_startup_marks_interrupted_lectures_failed(session_factory, db, stuck):
    user = User(email="y@example.com", password_hash="x")
    db.add(user)
    db.commit()
    stuck_lec = Lecture(user_id=user.id, title="Stuck", status=stuck)
    done = Lecture(user_id=user.id, title="Done", status="transcribed")
    db.add_all([stuck_lec, done])
    db.commit()

    assert mark_interrupted(session_factory) == 1

    db.expire_all()
    assert db.get(Lecture, stuck_lec.id).status == "failed"
    assert "restart" in db.get(Lecture, stuck_lec.id).error
    assert db.get(Lecture, done.id).status == "transcribed"
