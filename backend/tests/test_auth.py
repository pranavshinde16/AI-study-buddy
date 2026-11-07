from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select

from app.core.security import JWT_ALGORITHM
from app.models.user import User


def _assert_envelope(body: dict, code: str) -> None:
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert isinstance(body["error"]["details"], dict)


# --- register ---------------------------------------------------------------


def test_register_creates_user_and_hides_password(client, db):
    r = client.post(
        "/api/auth/register",
        json={"email": "Ada@Example.com", "password": "correct-horse-battery", "full_name": "  Ada  "},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "ada@example.com"  # normalised
    assert body["full_name"] == "Ada"
    assert "password" not in body and "password_hash" not in body

    user = db.scalar(select(User))
    assert user.password_hash.startswith("$2")  # bcrypt hash, never plain text
    assert "correct-horse-battery" not in user.password_hash


def test_register_duplicate_email_is_case_insensitive(client, make_user):
    make_user(email="ada@example.com")
    r = client.post("/api/auth/register", json={"email": "ADA@example.com", "password": "another-password"})
    assert r.status_code == 409
    _assert_envelope(r.json(), "EMAIL_TAKEN")


def test_register_validation_errors_use_envelope(client):
    r = client.post("/api/auth/register", json={"email": "not-an-email", "password": "short"})
    assert r.status_code == 422
    body = r.json()
    _assert_envelope(body, "VALIDATION_ERROR")
    fields = {tuple(e["loc"])[-1] for e in body["error"]["details"]["errors"]}
    assert {"email", "password"} <= fields


def test_register_rejects_password_longer_than_bcrypt_limit(client):
    r = client.post("/api/auth/register", json={"email": "a@example.com", "password": "é" * 40})  # 80 bytes
    assert r.status_code == 422
    _assert_envelope(r.json(), "VALIDATION_ERROR")


# --- login ------------------------------------------------------------------


def test_login_returns_jwt_and_me_works(client, make_user, settings):
    created = make_user()
    r = client.post("/api/auth/login", json={"email": "ADA@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 200
    token = r.json()
    assert token["token_type"] == "bearer"
    assert token["expires_in"] == settings.access_token_expire_minutes * 60

    payload = jwt.decode(token["access_token"], settings.secret_key, algorithms=[JWT_ALGORITHM])
    assert payload["sub"] == created["id"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"


def test_login_wrong_password_and_unknown_email_look_the_same(client, make_user):
    make_user()
    wrong = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "nope-nope-nope"})
    unknown = client.post("/api/auth/login", json={"email": "who@example.com", "password": "nope-nope-nope"})
    for r in (wrong, unknown):
        assert r.status_code == 401
        _assert_envelope(r.json(), "INVALID_CREDENTIALS")
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_login_disabled_account(client, make_user, db):
    make_user()
    user = db.scalar(select(User))
    user.is_active = False
    db.commit()
    r = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 401
    _assert_envelope(r.json(), "ACCOUNT_DISABLED")


# --- /me token handling -----------------------------------------------------


def test_me_requires_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    _assert_envelope(r.json(), "NOT_AUTHENTICATED")


def test_me_rejects_garbage_and_wrongly_signed_tokens(client, make_user, settings):
    created = make_user()
    forged = jwt.encode(
        {"sub": created["id"], "exp": datetime.now(UTC) + timedelta(hours=1), "type": "access"},
        "some-other-secret-that-is-at-least-32-bytes-long",
        algorithm=JWT_ALGORITHM,
    )
    for token in ("garbage", forged):
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        _assert_envelope(r.json(), "INVALID_TOKEN")


def test_me_rejects_expired_token(client, make_user, settings):
    created = make_user()
    expired = jwt.encode(
        {"sub": created["id"], "exp": datetime.now(UTC) - timedelta(minutes=1), "type": "access"},
        settings.secret_key,
        algorithm=JWT_ALGORITHM,
    )
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401
    _assert_envelope(r.json(), "TOKEN_EXPIRED")
