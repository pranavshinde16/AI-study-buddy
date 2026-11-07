"""Shared test fixtures. Tests use in-memory SQLite and fake LLM providers: no network, no Postgres."""

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
from app.db.session import get_db
from app.main import create_app


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
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        secret_key="test-secret-key-not-for-production-0123456789",
        groq_api_key="test-groq-key",
        openai_api_key="",
        log_json=False,
        llm_max_retries=3,
        llm_backoff_base_sec=2.0,
        llm_backoff_max_sec=30.0,
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
def app(settings, session_factory) -> FastAPI:
    application = create_app()

    def _get_db() -> Iterator[Session]:
        with session_factory() as s:
            yield s

    application.dependency_overrides[get_db] = _get_db
    application.dependency_overrides[get_settings] = lambda: settings
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
