"""Liveness endpoint + dependency checks: database and vector store (Chroma). The Ollama check
is added in Phase 10."""

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSession, Indexer
from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app_env: str
    version: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse, summary="Liveness check plus dependency checks")
def health(settings: Annotated[Settings, Depends(get_settings)], db: DbSession, indexer: Indexer) -> HealthResponse:
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except SQLAlchemyError as exc:
        log.warning("health_db_failed", error_type=type(exc).__name__)
        checks["database"] = "error"
    checks["vector_store"] = "ok" if indexer.store.heartbeat() else "error"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return HealthResponse(status=status, app_env=settings.app_env, version=settings.app_version, checks=checks)
