"""Grounded Q&A routes: /ask, /chat, chat sessions and history, and /models.
HTTP only; the logic lives in services/chat.py and services/rag.py (CLAUDE.md rule 6)."""

import uuid

from fastapi import APIRouter

from app.api.deps import AppSettings, CurrentUser, DbSession, Generators, Indexer, ModelRegistry, Rag
from app.schemas.errors import error_responses
from app.schemas.rag import (
    AskRequest,
    AskResponse,
    ChatHistoryOut,
    ChatRequest,
    ChatResponse,
    ChatSessionOut,
    GeneratorOut,
)
from app.services import chat as chat_service

router = APIRouter(tags=["ask & chat"])

_DESC = (
    "Answers only from this lecture's transcript. The question is embedded (with bge's search prefix), the "
    "top RAG_TOP_K chunks are retrieved, and if the best similarity is below RAG_MIN_SCORE the app refuses "
    "without calling the LLM. Otherwise the chosen generator answers from the numbered chunks and may still "
    "refuse (`answerable: false`) when they don't contain the answer. Source times come from the transcript. "
    "A lecture transcribed before indexing existed is indexed on its first question."
)


@router.post(
    "/lectures/{lecture_id}/ask",
    response_model=AskResponse,
    summary="Ask one grounded question about the lecture",
    description=_DESC,
    responses=error_responses(401, 404, 409, 422, 429, 502, 503),
)
def ask(lecture_id: uuid.UUID, body: AskRequest, user: CurrentUser, db: DbSession, settings: AppSettings,
        rag: Rag, indexer: Indexer) -> AskResponse:
    return AskResponse(**chat_service.ask(db, user, lecture_id, question=body.question, generator=body.model,
                                          settings=settings, rag=rag, indexer=indexer))


@router.post(
    "/lectures/{lecture_id}/chat",
    response_model=ChatResponse,
    summary="Multi-turn chat about the lecture (follow-ups are rewritten into standalone questions)",
    description=_DESC + " Send the returned `session_id` with the next message to continue the conversation.",
    responses=error_responses(401, 404, 409, 422, 429, 502, 503),
)
def chat(lecture_id: uuid.UUID, body: ChatRequest, user: CurrentUser, db: DbSession, settings: AppSettings,
         rag: Rag, indexer: Indexer) -> ChatResponse:
    return ChatResponse(**chat_service.chat(db, user, lecture_id, message=body.message, session_id=body.session_id,
                                            generator=body.model, settings=settings, rag=rag, indexer=indexer))


@router.get(
    "/lectures/{lecture_id}/chat",
    response_model=list[ChatSessionOut],
    summary="Your chat sessions for this lecture, newest first",
    responses=error_responses(401, 404),
)
def list_sessions(lecture_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[ChatSessionOut]:
    return [ChatSessionOut(**s) for s in chat_service.list_sessions(db, user, lecture_id)]


@router.get(
    "/lectures/{lecture_id}/chat/{session_id}",
    response_model=ChatHistoryOut,
    summary="Chat history with sources",
    responses=error_responses(401, 404),
)
def history(lecture_id: uuid.UUID, session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ChatHistoryOut:
    return ChatHistoryOut(**chat_service.get_history(db, user, lecture_id, session_id))


@router.get(
    "/models",
    response_model=list[GeneratorOut],
    summary="Answer generators you can pass as `model` to /ask and /chat",
    responses=error_responses(401),
)
def models(user: CurrentUser, db: DbSession, generators: Generators, registry: ModelRegistry) -> list[GeneratorOut]:
    versions = registry.generator_versions(db)  # DB only (no Ollama call), so the Ask page stays fast
    return [GeneratorOut(name=g.name, provider=g.provider, model=g.model, description=g.description,
                         **versions.get(g.name, {}))
            for g in generators.all()]
