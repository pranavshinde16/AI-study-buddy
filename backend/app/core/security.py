"""Password hashing (bcrypt) and JWT access tokens (PyJWT, HS256)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

JWT_ALGORITHM = "HS256"
BCRYPT_MAX_BYTES = 72  # bcrypt only uses the first 72 bytes; bcrypt>=5 rejects longer input


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, secret_key: str, expires_minutes: int) -> tuple[str, int]:
    """Return (token, expires_in_seconds). `subject` is the user id."""
    now = datetime.now(UTC)
    expires = timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {"sub": subject, "iat": now, "exp": now + expires, "type": "access"}
    return jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM), int(expires.total_seconds())


def decode_access_token(token: str, secret_key: str) -> dict[str, Any]:
    """Raise jwt.PyJWTError if the token is invalid or expired."""
    payload = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp"]})
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload
