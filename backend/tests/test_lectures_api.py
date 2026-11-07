"""/api/lectures endpoints: upload validation, background transcription, ownership, transcript
downloads and delete. Speech recognition is the FakeASRProvider (no network)."""

import uuid

import pytest
from sqlalchemy import select

from app.models.lecture import Lecture, TranscriptSegment
from app.models.llmops import PipelineRun
from tests.fakes import rate_limited
from tests.fixtures.audio import make_tone, make_video, needs_ffmpeg


def _upload(client, headers, path, *, content_type="audio/mpeg", title=None):
    data = {"title": title} if title else None
    with path.open("rb") as f:
        return client.post(
            "/api/lectures/upload", headers=headers, files={"file": (path.name, f, content_type)}, data=data
        )


def _login_other(client, make_user) -> dict:
    make_user(email="grace@example.com", password="another-long-password")
    r = client.post("/api/auth/login", json={"email": "grace@example.com", "password": "another-long-password"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@needs_ffmpeg
def test_upload_mp3_runs_pipeline_and_serves_transcript(client, auth_headers, tmp_path, settings):
    r = _upload(client, auth_headers, make_tone(tmp_path / "Intro_to-Neural Nets.mp3", 12))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["title"] == "Intro to Neural Nets" and body["status"] == "uploaded"
    lecture_id = body["lecture_id"]
    assert body["status_url"] == f"/api/lectures/{lecture_id}/status"

    # TestClient runs BackgroundTasks before returning, so the pipeline has finished here.
    st = client.get(body["status_url"], headers=auth_headers).json()
    assert st == {"status": "transcribed", "progress": 100, "stage_detail": st["stage_detail"], "error": None}

    meta = client.get(f"/api/lectures/{lecture_id}", headers=auth_headers).json()
    assert meta["duration_sec"] == pytest.approx(12, abs=0.2)
    assert meta["original_filename"] == "Intro_to-Neural Nets.mp3"

    tr = client.get(f"/api/lectures/{lecture_id}/transcript", headers=auth_headers).json()
    assert tr["language"] == "en"
    assert [(s["id"], s["start"], s["end"]) for s in tr["segments"]] == [
        (0, 0.0, 1.0), (1, 1.0, 1.9), (2, 10.0, 11.0), (3, 11.0, 11.9),
    ]

    srt = client.get(f"/api/lectures/{lecture_id}/transcript/download?format=srt", headers=auth_headers)
    assert srt.status_code == 200
    assert srt.headers["content-disposition"] == 'attachment; filename="Intro_to_Neural_Nets.srt"'
    assert srt.text.startswith("1\n00:00:00,000 --> 00:00:01,000\npart 1 hello\n")
    vtt = client.get(f"/api/lectures/{lecture_id}/transcript/download?format=vtt", headers=auth_headers)
    assert vtt.headers["content-type"].startswith("text/vtt") and vtt.text.startswith("WEBVTT")
    txt = client.get(f"/api/lectures/{lecture_id}/transcript/download", headers=auth_headers)
    assert txt.text.splitlines()[2] == "[00:10] part 2 hello"


@needs_ffmpeg
def test_upload_mp4_video_is_accepted(client, auth_headers, tmp_path):
    r = _upload(client, auth_headers, make_video(tmp_path / "lecture.mp4", 4), content_type="video/mp4", title="Week 1")
    assert r.status_code == 202, r.text
    assert r.json()["title"] == "Week 1"
    assert client.get(r.json()["status_url"], headers=auth_headers).json()["status"] == "transcribed"


def test_upload_requires_auth(client, tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    r = _upload(client, {}, f)
    assert r.status_code == 401 and r.json()["error"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.parametrize(
    ("name", "ctype"),
    [("notes.txt", "text/plain"), ("slides.pdf", "application/pdf"), ("noext", "audio/mpeg"), ("a.mp3", "image/png")],
)
def test_upload_rejects_unsupported_types(client, auth_headers, tmp_path, settings, name, ctype):
    f = tmp_path / name
    f.write_bytes(b"not audio")
    r = _upload(client, auth_headers, f, content_type=ctype)
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert not (settings.storage_path / "uploads").exists() or not any((settings.storage_path / "uploads").iterdir())


@needs_ffmpeg
def test_upload_rejects_fake_audio_and_cleans_up(client, auth_headers, tmp_path, settings, db):
    f = tmp_path / "fake.mp3"
    f.write_bytes(b"\x00" * 4096)
    r = _upload(client, auth_headers, f, content_type="application/octet-stream")
    assert r.status_code == 415, r.text
    assert not any((settings.storage_path / "uploads").iterdir())
    assert db.scalar(select(Lecture)) is None


def test_upload_too_large(client, auth_headers, tmp_path, settings, db):
    settings.max_upload_mb = 1
    f = tmp_path / "big.mp3"
    f.write_bytes(b"\x00" * (1024 * 1024 + 10))
    r = _upload(client, auth_headers, f)
    assert r.status_code == 413
    assert r.json()["error"] == {"code": "FILE_TOO_LARGE", "message": "File is larger than the 1 MB limit",
                                 "details": {"max_mb": 1}}
    assert not any((settings.storage_path / "uploads").iterdir())
    assert db.scalar(select(Lecture)) is None


@needs_ffmpeg
def test_pipeline_failure_is_visible_in_status(client, auth_headers, tmp_path, fake_asr):
    fake_asr.script = [rate_limited()] * 4
    r = _upload(client, auth_headers, make_tone(tmp_path / "a.mp3", 3))
    st = client.get(r.json()["status_url"], headers=auth_headers).json()
    assert st["status"] == "failed" and "rate limit" in st["error"]
    tr = client.get(f"/api/lectures/{r.json()['lecture_id']}/transcript", headers=auth_headers)
    assert tr.status_code == 409 and tr.json()["error"]["code"] == "LECTURE_NOT_READY"


def test_transcript_not_ready_returns_409(client, auth_headers, db):
    me = client.get("/api/auth/me", headers=auth_headers).json()
    lec = Lecture(user_id=uuid.UUID(me["id"]), title="Pending", status="transcribing", progress=40)
    db.add(lec)
    db.commit()
    r = client.get(f"/api/lectures/{lec.id}/transcript", headers=auth_headers)
    assert r.status_code == 409
    assert r.json()["error"]["details"] == {"status": "transcribing", "progress": 40}
    bad = client.get(f"/api/lectures/{lec.id}/transcript/download?format=docx", headers=auth_headers)
    assert bad.status_code == 422


@needs_ffmpeg
def test_other_users_cannot_see_or_delete(client, auth_headers, make_user, tmp_path):
    lecture_id = _upload(client, auth_headers, make_tone(tmp_path / "mine.mp3", 3)).json()["lecture_id"]
    other = _login_other(client, make_user)

    assert client.get("/api/lectures", headers=other).json() == []
    for method, path in [
        ("get", f"/api/lectures/{lecture_id}"),
        ("get", f"/api/lectures/{lecture_id}/status"),
        ("get", f"/api/lectures/{lecture_id}/transcript"),
        ("get", f"/api/lectures/{lecture_id}/transcript/download?format=srt"),
        ("delete", f"/api/lectures/{lecture_id}"),
    ]:
        r = getattr(client, method)(path, headers=other)
        assert r.status_code == 404 and r.json()["error"]["code"] == "LECTURE_NOT_FOUND", path

    mine = client.get("/api/lectures", headers=auth_headers).json()
    assert [lec["id"] for lec in mine] == [lecture_id]


def test_unknown_and_malformed_ids(client, auth_headers):
    assert client.get(f"/api/lectures/{uuid.uuid4()}", headers=auth_headers).status_code == 404
    assert client.get("/api/lectures/not-a-uuid", headers=auth_headers).status_code == 422


@needs_ffmpeg
def test_delete_removes_rows_and_files(client, auth_headers, tmp_path, settings, db):
    lecture_id = _upload(client, auth_headers, make_tone(tmp_path / "bye.mp3", 3)).json()["lecture_id"]
    lid = uuid.UUID(lecture_id)
    assert (settings.storage_path / "uploads" / lecture_id).exists()

    r = client.delete(f"/api/lectures/{lecture_id}", headers=auth_headers)
    assert r.status_code == 204 and r.content == b""

    db.expire_all()
    assert db.get(Lecture, lid) is None
    assert db.scalar(select(TranscriptSegment).where(TranscriptSegment.lecture_id == lid)) is None
    assert db.scalar(select(PipelineRun).where(PipelineRun.lecture_id == lid)) is None
    assert not (settings.storage_path / "uploads" / lecture_id).exists()
    assert client.get(f"/api/lectures/{lecture_id}", headers=auth_headers).status_code == 404


@needs_ffmpeg
def test_media_serves_the_recording_with_its_content_type(client, auth_headers, tmp_path, make_user):
    src = make_tone(tmp_path / "Week 2.mp3", 3)
    lecture_id = _upload(client, auth_headers, src, content_type="application/octet-stream").json()["lecture_id"]

    r = client.get(f"/api/lectures/{lecture_id}/media", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.content == src.read_bytes()

    # Range requests work, so the browser could seek without the whole file.
    part = client.get(f"/api/lectures/{lecture_id}/media", headers={**auth_headers, "Range": "bytes=0-9"})
    assert part.status_code == 206 and part.content == src.read_bytes()[:10]

    assert client.get(f"/api/lectures/{lecture_id}/media").status_code == 401
    other = client.get(f"/api/lectures/{lecture_id}/media", headers=_login_other(client, make_user))
    assert other.status_code == 404 and other.json()["error"]["code"] == "LECTURE_NOT_FOUND"


@needs_ffmpeg
def test_media_mp4_is_video(client, auth_headers, tmp_path):
    r = _upload(client, auth_headers, make_video(tmp_path / "v.mp4", 2), content_type="video/mp4")
    media = client.get(f"/api/lectures/{r.json()['lecture_id']}/media", headers=auth_headers)
    assert media.status_code == 200 and media.headers["content-type"] == "video/mp4"


@needs_ffmpeg
def test_media_missing_file_returns_404(client, auth_headers, tmp_path, settings, db):
    lecture_id = _upload(client, auth_headers, make_tone(tmp_path / "gone.mp3", 2)).json()["lecture_id"]
    for f in (settings.storage_path / "uploads" / lecture_id).iterdir():
        f.unlink()
    r = client.get(f"/api/lectures/{lecture_id}/media", headers=auth_headers)
    assert r.status_code == 404 and r.json()["error"]["code"] == "MEDIA_NOT_FOUND"

    # A lecture row with no stored path at all.
    me = client.get("/api/auth/me", headers=auth_headers).json()
    lec = Lecture(user_id=uuid.UUID(me["id"]), title="No file", status="transcribed", progress=100)
    db.add(lec)
    db.commit()
    r = client.get(f"/api/lectures/{lec.id}/media", headers=auth_headers)
    assert r.status_code == 404 and r.json()["error"]["code"] == "MEDIA_NOT_FOUND"
