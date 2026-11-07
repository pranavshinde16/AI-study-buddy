"""Shared test fixtures. Tests use in-memory SQLite and fake LLM providers: no network, no Postgres."""

import random
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register all tables)
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.api.deps import (
    get_flashcard_generator_dep,
    get_generator_dep,
    get_grader_dep,
    get_pipeline_dep,
    get_quiz_generator_dep,
)
from app.db.session import get_db
from app.main import create_app
from app.services.asr.client import ASRClient
from app.services.embeddings import EmbeddingClient
from app.services.generation.flashcards import FlashcardGenerator
from app.services.generation.quiz import QuizGenerator
from app.services.generation.summary import LectureGenerator
from app.services.grading import ShortAnswerGrader
from app.services.llm.client import LLMClient
from app.services.llm.pricing import load_pricing
from app.services.llm.prompts import PromptRegistry
from app.services.media import media_from_settings
from app.services.storage import LocalStorage
from app.workers.pipeline import Pipeline
from tests.fakes import FakeASRProvider, FakeEmbedder, FakeLectureLLM, FakeProvider


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """CLAUDE.md rule 7: any connection to a non-loopback address fails the test.

    Loopback is allowed because asyncio on Windows builds its event-loop wake-up pipe from a
    local socket pair (127.0.0.1); nothing leaves the machine.
    """
    import socket

    real_connect = socket.socket.connect

    def _guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "::1", "localhost") or self.family == getattr(socket, "AF_UNIX", object()):
            return real_connect(self, address)
        raise RuntimeError(f"Network access to {address!r} is not allowed in tests; use a fake provider")

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        storage_dir=str(tmp_path / "storage"),
        asr_provider="groq",
        asr_chunk_sec=10,
        app_env="test",
        secret_key="test-secret-key-not-for-production-0123456789",
        groq_api_key="test-groq-key",
        openai_api_key="",
        log_json=False,
        llm_max_retries=3,
        llm_backoff_base_sec=2.0,
        llm_backoff_max_sec=30.0,
        groq_tokens_per_minute=0,  # pacing has its own tests; keep the others instant
        summary_auto=False,  # Phase 4 tests stop at `transcribed`; summary tests turn it on
    )


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared in-memory DB across sessions
    )

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory) -> Iterator[Session]:
    with session_factory() as s:
        yield s


@pytest.fixture
def fake_asr() -> FakeASRProvider:
    """Replace `.script` / `.on_call` in a test to change what speech recognition returns."""
    return FakeASRProvider("groq")


@pytest.fixture
def asr_client(settings, session_factory, fake_asr) -> ASRClient:
    return ASRClient(settings, session_factory, load_pricing(), providers={"groq": fake_asr}, sleep=lambda _s: None)


@pytest.fixture
def storage(settings) -> LocalStorage:
    return LocalStorage(settings.storage_path)


@pytest.fixture
def fake_llm() -> FakeLectureLLM:
    """Answers the topics/notes/summary prompts; set `.fail[task]` / `.invalid[task]` to break one."""
    return FakeLectureLLM()


@pytest.fixture
def llm_provider(fake_llm) -> FakeProvider:
    return FakeProvider("groq", responder=fake_llm)


@pytest.fixture
def lecture_llm_client(settings, session_factory, llm_provider) -> LLMClient:
    return LLMClient(settings, session_factory, PromptRegistry(), load_pricing(),
                     providers={"groq": llm_provider}, sleep=lambda _s: None, rate_limiters={})


@pytest.fixture
def generator(settings, lecture_llm_client) -> LectureGenerator:
    return LectureGenerator(settings, lecture_llm_client)


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """Bag-of-words vectors; set `.fail = SomeError()` to make embedding fail."""
    return FakeEmbedder()


@pytest.fixture
def embedding_client(settings, session_factory, fake_embedder) -> EmbeddingClient:
    return EmbeddingClient(settings, session_factory, load_pricing(), embedder=fake_embedder)


@pytest.fixture
def quiz_generator(settings, lecture_llm_client) -> QuizGenerator:
    return QuizGenerator(settings, lecture_llm_client, rng=random.Random(0))


@pytest.fixture
def grader(settings, lecture_llm_client, embedding_client) -> ShortAnswerGrader:
    return ShortAnswerGrader(settings, lecture_llm_client, embedding_client)


@pytest.fixture
def flashcard_generator(settings, lecture_llm_client) -> FlashcardGenerator:
    return FlashcardGenerator(settings, lecture_llm_client)


@pytest.fixture
def pipeline(settings, session_factory, storage, asr_client, generator) -> Pipeline:
    return Pipeline(settings, session_factory, storage, media_from_settings(settings), asr_client, generator)


@pytest.fixture
def app(settings, session_factory, pipeline, generator, quiz_generator, grader, flashcard_generator) -> FastAPI:
    application = create_app()

    def _get_db() -> Iterator[Session]:
        with session_factory() as s:
            yield s

    application.dependency_overrides[get_db] = _get_db
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_pipeline_dep] = lambda: pipeline
    application.dependency_overrides[get_generator_dep] = lambda: generator
    application.dependency_overrides[get_quiz_generator_dep] = lambda: quiz_generator
    application.dependency_overrides[get_grader_dep] = lambda: grader
    application.dependency_overrides[get_flashcard_generator_dep] = lambda: flashcard_generator
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def make_user(client):
    def _make(email: str = "ada@example.com", password: str = "correct-horse-battery", full_name: str | None = "Ada"):
        r = client.post("/api/auth/register", json={"email": email, "password": password, "full_name": full_name})
        assert r.status_code == 201, r.text
        return r.json()

    return _make


@pytest.fixture
def auth_headers(client, make_user):
    make_user()
    r = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def make_ready_lecture(client, auth_headers, db):
    """A lecture with a stored transcript whose summary + topic notes were generated through the
    real POST /summarize path (fake LLM). With n=12 the notes have two topics:
    "Topic 0" (segments 0-6) and "Topic 5" (segments 7-11). Segment i runs i*10 .. i*10+9.5 s."""
    import uuid as _uuid

    from app.models.lecture import Lecture, TranscriptSegment

    def _make(n: int = 12, headers=None, summarize: bool = True) -> _uuid.UUID:
        h = headers or auth_headers
        me = client.get("/api/auth/me", headers=h).json()
        lec = Lecture(user_id=_uuid.UUID(me["id"]), title="Cell energy", status="transcribed", progress=100,
                      duration_sec=n * 10.0)
        db.add(lec)
        db.flush()
        db.add_all(
            TranscriptSegment(lecture_id=lec.id, idx=i, start_sec=i * 10.0, end_sec=i * 10.0 + 9.5,
                              text=f"sentence {i} about how cells turn food into energy")
            for i in range(n)
        )
        db.commit()
        if summarize:
            r = client.post(f"/api/lectures/{lec.id}/summarize", headers=h)
            assert r.status_code == 200, r.text
        return lec.id

    return _make
