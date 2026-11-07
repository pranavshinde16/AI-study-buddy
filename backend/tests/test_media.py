"""ffmpeg/ffprobe wrapper: probing, 16 kHz mono FLAC extraction, chunk offsets, re-splitting."""

import json
import subprocess

import pytest

from app.services.media import Media, MediaError, UnsupportedMediaError
from tests.fixtures.audio import make_tone, make_video, needs_ffmpeg


@pytest.fixture
def media() -> Media:
    return Media("ffmpeg", "ffprobe", timeout_sec=120)


def _stream_info(path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)["streams"][0]


@needs_ffmpeg
@pytest.mark.parametrize("name", ["tone.mp3", "tone.wav", "tone.m4a"])
def test_probe_reads_duration(media, tmp_path, name):
    info = media.probe(make_tone(tmp_path / name, 3))
    assert info.has_audio and info.duration_sec == pytest.approx(3, abs=0.15)


@needs_ffmpeg
def test_probe_video_with_audio(media, tmp_path):
    assert media.probe(make_video(tmp_path / "v.mp4", 3)).duration_sec == pytest.approx(3, abs=0.2)


@needs_ffmpeg
def test_probe_rejects_video_without_audio(media, tmp_path):
    with pytest.raises(UnsupportedMediaError, match="no audio track"):
        media.probe(make_video(tmp_path / "silent.mp4", 2, with_audio=False))


@needs_ffmpeg
def test_probe_rejects_non_media(media, tmp_path):
    fake = tmp_path / "notes.mp3"
    fake.write_text("this is not audio", encoding="utf-8")
    with pytest.raises(UnsupportedMediaError):
        media.probe(fake)


@needs_ffmpeg
def test_extract_chunks_offsets_and_format(media, tmp_path):
    src = make_tone(tmp_path / "lecture.mp3", 25)
    chunks = media.extract_chunks(src, tmp_path / "audio", chunk_sec=10, max_chunk_bytes=24 * 1024 * 1024)

    assert len(chunks) == 3
    assert [c.index for c in chunks] == [0, 1, 2]
    assert chunks[0].offset_sec == 0.0
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.offset_sec == pytest.approx(prev.offset_sec + prev.duration_sec, abs=0.01)  # continuous
    assert sum(c.duration_sec for c in chunks) == pytest.approx(25, abs=0.2)
    info = _stream_info(chunks[0].path)
    assert (info["codec_name"], info["sample_rate"], info["channels"]) == ("flac", "16000", 1)


@needs_ffmpeg
def test_oversized_chunks_are_split_again(media, tmp_path):
    src = make_tone(tmp_path / "long.wav", 70)
    chunks = media.extract_chunks(src, tmp_path / "audio", chunk_sec=70, max_chunk_bytes=1)  # everything "too big"

    assert len(chunks) > 1
    assert all(c.duration_sec <= 36 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.offset_sec == pytest.approx(prev.offset_sec + prev.duration_sec, abs=0.01)
    assert sum(c.duration_sec for c in chunks) == pytest.approx(70, abs=0.3)


def test_missing_ffmpeg_gives_clear_error(tmp_path):
    with pytest.raises(MediaError) as exc:
        Media("definitely-not-ffmpeg", "definitely-not-ffprobe").probe(tmp_path / "x.mp3")
    assert exc.value.code == "FFMPEG_NOT_FOUND"
    assert exc.value.status_code == 503
