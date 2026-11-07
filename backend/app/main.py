"""FastAPI app factory: builds the app, adds middleware, error handlers and routers under /api.

Run:  uvicorn app.main:app --reload   (from the backend/ folder)
"""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, health
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestIdMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Turns recorded lectures into transcripts, notes, quizzes, flashcards and grounded Q&A.\n\n"
            "**Auth:** call `POST /api/auth/login`, copy `access_token`, click **Authorize** and paste it.\n\n"
            'All errors use one envelope: `{"error": {"code", "message", "details"}}`.'
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    register_error_handlers(app)

    # Middleware runs outermost-last: CORS wraps request-id so CORS headers are on every response.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(auth.router)
    app.include_router(api)

    return app


app = create_app()
