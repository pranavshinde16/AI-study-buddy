"""Account creation and login. Routers call these; no HTTP details here."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import hash_password, verify_password
from app.models.user import User

# Hash used to keep login timing similar whether or not the e-mail exists.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def register_user(db: Session, email: str, password: str, full_name: str | None) -> User:
    email = _normalise_email(email)
    if db.scalar(select(User.id).where(func.lower(User.email) == email)) is not None:
        raise ConflictError("An account with this e-mail already exists", code="EMAIL_TAKEN")
    user = User(email=email, password_hash=hash_password(password), full_name=full_name)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:  # concurrent registration with the same e-mail
        db.rollback()
        raise ConflictError("An account with this e-mail already exists", code="EMAIL_TAKEN") from exc
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(func.lower(User.email) == _normalise_email(email)))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise UnauthorizedError("Incorrect e-mail or password", code="INVALID_CREDENTIALS")
    if not verify_password(password, user.password_hash):
        raise UnauthorizedError("Incorrect e-mail or password", code="INVALID_CREDENTIALS")
    if not user.is_active:
        raise UnauthorizedError("This account is disabled", code="ACCOUNT_DISABLED")
    return user


def get_active_user(db: Session, user_id: uuid.UUID) -> User | None:
    user = db.get(User, user_id)
    return user if user is not None and user.is_active else None
