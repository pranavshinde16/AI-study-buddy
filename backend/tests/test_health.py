from app.core.config import Settings


def test_health_returns_ok_with_db_and_vector_store_checks(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app_env": "test",
        "version": "0.1.0",
        "checks": {"database": "ok", "vector_store": "ok"},
    }


def test_health_degraded_when_vector_store_fails(client, vector_store, monkeypatch):
    monkeypatch.setattr(vector_store, "heartbeat", lambda: False)
    body = client.get("/api/health").json()
    assert body["status"] == "degraded" and body["checks"]["vector_store"] == "error"


def test_openapi_docs_available(client):
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_free_tier_is_default():
    """OpenAI (paid) must never be the default provider."""
    s = Settings(_env_file=None)
    assert s.llm_provider == "groq"
    assert s.asr_provider == "groq"


def test_production_refuses_default_secret():
    import pytest
    from pydantic import ValidationError

    for weak in ("change-me", "too-short"):
        with pytest.raises(ValidationError, match="SECRET_KEY"):
            Settings(_env_file=None, app_env="production", secret_key=weak)
    Settings(_env_file=None, app_env="production", secret_key="x" * 32)  # long enough: accepted
