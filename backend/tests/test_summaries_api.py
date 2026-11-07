"""POST /lectures/{id}/summarize and GET /lectures/{id}/notes: caching, regenerate, status flow,
failures without losing the transcript, ownership, and the automatic pipeline step."""

import uuid

import pytest
from sqlalchemy import select

from app.models.lecture import Lecture, LectureOutput, TranscriptSegment
from app.models.llmops import LLMCall
from app.services.llm.providers import ProviderError
from app.workers.pipeline import mark_interrupted
from tests.fakes import rate_limited
from tests.fixtures.audio import make_tone, needs_ffmpeg


@pytest.fixture
def make_lecture(client, auth_headers, db):
    """A lecture with a stored transcript (no ffmpeg needed)."""

    def _make(status: str = "transcribed", n: int = 12, headers=None) -> uuid.UUID:
        me = client.get("/api/auth/me", headers=headers or auth_headers).json()
        lec = Lecture(user_id=uuid.UUID(me["id"]), title="Backprop", status=status, progress=100, duration_sec=n * 10.0)
        db.add(lec)
        db.flush()
        db.add_all(
            TranscriptSegment(lecture_id=lec.id, idx=i, start_sec=i * 10.0, end_sec=i * 10.0 + 9.5, text=f"sentence {i}")
            for i in range(n)
        )
        db.commit()
        return lec.id

    return _make


def _calls(db, task=None) -> list[LLMCall]:
    q = select(LLMCall)
    if task:
        q = q.where(LLMCall.task == task)
    return list(db.scalars(q))


def test_summarize_generates_caches_and_regenerates(client, auth_headers, make_lecture, db, fake_llm):
    lid = make_lecture()

    r = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is False
    assert body["summary"] and body["key_takeaways"] == ["Takeaway one", "Takeaway two"]
    assert body["revision_notes_md"].startswith("- revise")
    assert body["definitions"][0] == {"term": "Term 0", "definition": "as explained (not stated in lecture)",
                                      "timestamp": 0.0}
    assert [(t["title"], t["start"], t["end"]) for t in body["topics"]] == [
        ("Topic 0", 0.0, 69.5), ("Topic 5", 70.0, 119.5),
    ]
    assert all(0 <= t["start"] < t["end"] <= 120 for t in body["topics"])  # inside the lecture
    assert body["meta"]["prompt_version"] == "summary@v1" and body["meta"]["model"] == "openai/gpt-oss-120b"
    assert {c.task for c in _calls(db)} == {"topics", "notes", "summary"}
    assert {c.prompt_version for c in _calls(db, "summary")} == {"summary@v1"}
    assert all(c.lecture_id == lid and c.status == "ok" for c in _calls(db))

    st = client.get(f"/api/lectures/{lid}/status", headers=auth_headers).json()
    assert st["status"] == "ready" and st["progress"] == 100 and st["error"] is None

    # Second call: served from the cache, no LLM calls.
    n_calls = len(fake_llm.tasks)
    again = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers)
    assert again.status_code == 200 and again.json()["cached"] is True
    assert len(fake_llm.tasks) == n_calls
    assert again.json()["summary"] == body["summary"]

    # regenerate=true runs the LLM again and replaces the cached rows.
    regen = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers, json={"regenerate": True})
    assert regen.status_code == 200 and regen.json()["cached"] is False
    assert len(fake_llm.tasks) == 2 * n_calls
    assert db.scalar(select(LectureOutput.id).where(LectureOutput.lecture_id == lid, LectureOutput.kind == "summary"))
    assert len(list(db.scalars(select(LectureOutput).where(LectureOutput.lecture_id == lid)))) == 2


def test_notes_endpoint(client, auth_headers, make_lecture):
    lid = make_lecture()
    r = client.get(f"/api/lectures/{lid}/notes", headers=auth_headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOTES_NOT_GENERATED"

    client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers)
    notes = client.get(f"/api/lectures/{lid}/notes", headers=auth_headers).json()
    assert [t["title"] for t in notes["topics"]] == ["Topic 0", "Topic 5"]
    assert notes["topics"][0]["notes_md"] == "- **Topic 0** notes from the transcript"
    assert notes["meta"]["prompt_versions"]["notes"] == "notes@v1"


@pytest.mark.parametrize("status", ["uploaded", "extracting_audio", "transcribing", "failed"])
def test_summarize_before_transcript_is_409(client, auth_headers, make_lecture, status):
    lid = make_lecture(status=status)
    r = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "LECTURE_NOT_READY"


def test_summarize_while_generating_is_409(client, auth_headers, make_lecture):
    lid = make_lecture(status="generating")
    r = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "GENERATION_IN_PROGRESS"
    n = client.get(f"/api/lectures/{lid}/notes", headers=auth_headers)
    assert n.status_code == 409 and n.json()["error"]["code"] == "GENERATION_IN_PROGRESS"


def test_rate_limit_keeps_transcript_and_allows_retry(client, auth_headers, make_lecture, fake_llm, db):
    lid = make_lecture()
    fake_llm.fail["summary"] = rate_limited(retry_after=5)

    r = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers)
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    assert "no paid fallback" in r.json()["error"]["message"]
    st = client.get(f"/api/lectures/{lid}/status", headers=auth_headers).json()
    assert st["status"] == "transcribed" and st["error"].startswith("Summary generation failed")
    assert client.get(f"/api/lectures/{lid}/transcript", headers=auth_headers).status_code == 200
    assert db.scalar(select(LectureOutput).where(LectureOutput.lecture_id == lid)) is None  # nothing half-saved
    assert {c.provider for c in _calls(db)} == {"groq"}

    del fake_llm.fail["summary"]
    ok = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers)
    assert ok.status_code == 200
    assert client.get(f"/api/lectures/{lid}/status", headers=auth_headers).json()["status"] == "ready"


def test_failed_regeneration_keeps_previous_result(client, auth_headers, make_lecture, fake_llm):
    lid = make_lecture()
    first = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers).json()
    fake_llm.fail["topics"] = ProviderError("model_not_found", "decommissioned", error_type="BadRequestError")

    r = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers, json={"regenerate": True})
    assert r.status_code == 503 and r.json()["error"]["code"] == "MODEL_UNAVAILABLE"

    st = client.get(f"/api/lectures/{lid}/status", headers=auth_headers).json()
    assert st["status"] == "ready" and st["error"] is None and "previous summary is kept" in st["stage_detail"]
    cached = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers).json()
    assert cached["cached"] is True and cached["summary"] == first["summary"]


def test_other_user_gets_404(client, auth_headers, make_lecture, make_user):
    lid = make_lecture()
    make_user(email="eve@example.com", password="eve-long-password")
    tok = client.post("/api/auth/login", json={"email": "eve@example.com", "password": "eve-long-password"}).json()
    other = {"Authorization": f"Bearer {tok['access_token']}"}
    assert client.post(f"/api/lectures/{lid}/summarize", headers=other).status_code == 404
    assert client.get(f"/api/lectures/{lid}/notes", headers=other).status_code == 404


def test_startup_sweep_returns_generating_to_transcribed(make_lecture, session_factory, db):
    lid = make_lecture(status="generating")
    assert mark_interrupted(session_factory) == 1
    db.expire_all()
    lec = db.get(Lecture, lid)
    assert lec.status == "transcribed" and "interrupted" in lec.error


@needs_ffmpeg
def test_pipeline_runs_summary_after_transcription(client, auth_headers, tmp_path, settings, fake_llm, db):
    settings.summary_auto = True
    with make_tone(tmp_path / "talk.mp3", 12).open("rb") as f:
        r = client.post("/api/lectures/upload", headers=auth_headers, files={"file": ("talk.mp3", f, "audio/mpeg")})
    lid = r.json()["lecture_id"]

    st = client.get(f"/api/lectures/{lid}/status", headers=auth_headers).json()
    assert st["status"] == "ready" and st["progress"] == 100, st
    assert fake_llm.tasks[0] == "topics" and fake_llm.tasks[-1] == "summary"
    s = client.post(f"/api/lectures/{lid}/summarize", headers=auth_headers).json()
    assert s["cached"] is True
    assert all(0 <= t["start"] <= t["end"] <= 12.5 for t in s["topics"])


@needs_ffmpeg
def test_pipeline_summary_failure_leaves_lecture_transcribed(client, auth_headers, tmp_path, settings, fake_llm):
    settings.summary_auto = True
    fake_llm.fail["notes"] = rate_limited()
    with make_tone(tmp_path / "talk.mp3", 5).open("rb") as f:
        r = client.post("/api/lectures/upload", headers=auth_headers, files={"file": ("talk.mp3", f, "audio/mpeg")})
    st = client.get(r.json()["status_url"], headers=auth_headers).json()
    assert st["status"] == "transcribed" and "rate limit" in st["error"]
    assert client.get(f"/api/lectures/{r.json()['lecture_id']}/transcript", headers=auth_headers).status_code == 200
