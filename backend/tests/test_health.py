from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app


def test_health_returns_ok():
    app = create_app()
    # Ignore any local .env so the test is deterministic.
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, app_env="test")
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app_env": "test", "version": "0.1.0"}


def test_openapi_docs_available():
    client = TestClient(create_app())
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_free_tier_is_default():
    """OpenAI (paid) must never be the default provider."""
    s = Settings(_env_file=None)
    assert s.llm_provider == "groq"
    assert s.asr_provider == "groq"
