"""FastAPI app factory: builds the app, adds middleware and mounts routers under /api.

Run:  uvicorn app.main:app --reload   (from the backend/ folder)
"""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import health
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Turns recorded lectures into transcripts, notes, quizzes, flashcards and grounded Q&A.",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    app.include_router(api)

    return app


app = create_app()
