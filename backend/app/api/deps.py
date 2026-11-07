"""Shared FastAPI dependencies: DB session, settings, current user, storage, ffmpeg, pipeline, generator."""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services.auth import get_active_user
from app.services.generation.flashcards import FlashcardGenerator, get_flashcard_generator
from app.services.generation.quiz import QuizGenerator, get_quiz_generator
from app.services.generation.summary import LectureGenerator, get_lecture_generator
from app.services.grading import ShortAnswerGrader, get_short_answer_grader
from app.services.indexing import LectureIndexer, get_indexer
from app.services.llm.generators import GeneratorRegistry, get_generator_registry
from app.services.rag import RagService, get_rag_service
from app.services.media import Media, media_from_settings
from app.services.storage import StorageService, storage_from_settings
from app.workers.pipeline import Pipeline, get_pipeline

# auto_error=False so we can return our own error envelope instead of FastAPI's default.
_bearer = HTTPBearer(auto_error=False, description="Paste the access_token from POST /api/auth/login")

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_current_user(
    db: DbSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Not authenticated", code="NOT_AUTHENTICATED")
    try:
        payload = decode_access_token(credentials.credentials, settings.secret_key)
        user_id = uuid.UUID(payload["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token has expired", code="TOKEN_EXPIRED") from exc
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise UnauthorizedError("Invalid token", code="INVALID_TOKEN") from exc

    user = get_active_user(db, user_id)
    if user is None:
        raise UnauthorizedError("User not found or inactive", code="INVALID_TOKEN")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_storage_dep(settings: AppSettings) -> StorageService:
    return storage_from_settings(settings)


def get_media_dep(settings: AppSettings) -> Media:
    return media_from_settings(settings)


def get_generator_dep() -> LectureGenerator:
    """Overridden in tests with a generator that uses a fake LLM provider."""
    return get_lecture_generator()


def get_quiz_generator_dep() -> QuizGenerator:
    return get_quiz_generator()


def get_grader_dep() -> ShortAnswerGrader:
    """The embedding model inside is loaded only when the fallback is first needed."""
    return get_short_answer_grader()


def get_flashcard_generator_dep() -> FlashcardGenerator:
    return get_flashcard_generator()


def get_rag_dep() -> RagService:
    """The embedding model and Chroma open lazily on the first question, not at startup."""
    return get_rag_service()


def get_indexer_dep() -> LectureIndexer:
    return get_indexer()


def get_generators_dep() -> GeneratorRegistry:
    return get_generator_registry()


def get_pipeline_dep() -> Pipeline:
    """Overridden in tests with a pipeline that uses the test DB and a fake ASR provider."""
    return get_pipeline()


Storage = Annotated[StorageService, Depends(get_storage_dep)]
MediaTools = Annotated[Media, Depends(get_media_dep)]
LecturePipeline = Annotated[Pipeline, Depends(get_pipeline_dep)]
Generator = Annotated[LectureGenerator, Depends(get_generator_dep)]
QuizGen = Annotated[QuizGenerator, Depends(get_quiz_generator_dep)]
Grader = Annotated[ShortAnswerGrader, Depends(get_grader_dep)]
FlashcardGen = Annotated[FlashcardGenerator, Depends(get_flashcard_generator_dep)]
Rag = Annotated[RagService, Depends(get_rag_dep)]
Indexer = Annotated[LectureIndexer, Depends(get_indexer_dep)]
Generators = Annotated[GeneratorRegistry, Depends(get_generators_dep)]
