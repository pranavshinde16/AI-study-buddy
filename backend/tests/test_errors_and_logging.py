from fastapi.testclient import TestClient

from app.core.errors import AppError


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "NOT_FOUND", "message": "Not Found", "details": {}}}


def test_app_error_and_unhandled_exception_use_envelope(app):
    @app.get("/api/_test/app-error")
    def _app_error():
        raise AppError("Lecture is still processing", code="LECTURE_NOT_READY", status_code=409, details={"x": 1})

    @app.get("/api/_test/boom")
    def _boom():
        raise RuntimeError("secret internal detail")

    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/api/_test/app-error")
    assert r.status_code == 409
    assert r.json() == {"error": {"code": "LECTURE_NOT_READY", "message": "Lecture is still processing", "details": {"x": 1}}}

    r = client.get("/api/_test/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["details"] == {"error_type": "RuntimeError"}
    assert "secret internal detail" not in r.text  # internals never leak to the client


def test_request_id_is_generated_and_echoed(client):
    generated = client.get("/api/health").headers["x-request-id"]
    assert len(generated) == 32

    echoed = client.get("/api/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"]
    assert echoed == "abc-123"

    # Unsafe incoming ids are replaced, not reflected.
    replaced = client.get("/api/health", headers={"X-Request-ID": "<script>"}).headers["x-request-id"]
    assert replaced != "<script>" and len(replaced) == 32


def test_request_log_line_contains_request_id(client, capsys):
    client.get("/api/health", headers={"X-Request-ID": "trace-me-42"})
    out = capsys.readouterr().out
    assert "trace-me-42" in out
    assert "/api/health" in out
