"""The single entry point for text embeddings (CLAUDE.md rule 4).

    client = get_embedding_client()
    vectors = client.embed(["first text", "second text"], task="grade_embedding", lecture_id=...)

- Model: EMBEDDING_MODEL (BAAI/bge-small-en-v1.5), run locally with sentence-transformers. It is
  free and needs no API key. The model is loaded on the FIRST call (not at app startup) and kept
  in a process-wide singleton, so the ~130 MB download and the load happen only once.
- Vectors are L2-normalised, so cosine similarity is a plain dot product (`cosine()`).
- Every call writes one `llm_calls` row (provider="local", cost 0, latency, status).
- Phase 6 uses it as the short-answer grading fallback; Phase 7 reuses it for RAG indexing/search.
"""

import hashlib
import math
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import Protocol

import structlog
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models.llmops import LLMCall
from app.services.llm.calllog import save_call
from app.services.llm.errors import LLMError, ProviderNotConfiguredError
from app.services.llm.pricing import PricingTable

log = structlog.get_logger(__name__)

PROVIDER = "local"


class Embedder(Protocol):
    model_name: str

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalised vector per text."""
        ...


class SentenceTransformerEmbedder:
    """Lazy wrapper around sentence-transformers. Importing this module does not import torch."""

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        self.model_name = model_name
        self.device = device
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the model now (called by EmbeddingClient before timing, so the one-time load
        is not counted as request latency in llm_calls; it is logged as embedding_model_loaded)."""
        self._load()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                    except ImportError as exc:
                        raise ProviderNotConfiguredError(
                            "sentence-transformers is not installed; run `pip install -r requirements.txt`.",
                            details={"provider": PROVIDER, "model": self.model_name},
                        ) from exc
                    log.info("embedding_model_loading", model=self.model_name, device=self.device)
                    start = time.perf_counter()
                    self._model = SentenceTransformer(self.model_name, device=self.device)
                    log.info("embedding_model_loaded", model=self.model_name,
                             load_ms=round((time.perf_counter() - start) * 1000, 1))
        return self._model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def encode(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        return [[float(x) for x in v] for v in vectors]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; works for normalised and unnormalised vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class EmbeddingClient:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session] | Callable[[], Session],
        pricing: PricingTable,
        embedder: Embedder | None = None,
    ) -> None:
        self.settings = settings
        self._session_factory = session_factory
        self.pricing = pricing
        self._embedder = embedder

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    def embed(
        self,
        texts: Sequence[str],
        *,
        task: str = "embedding",
        lecture_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
    ) -> list[list[float]]:
        items = [t if t.strip() else " " for t in texts]
        if not items:
            return []
        embedder = self.embedder
        model = embedder.model_name
        request_hash = hashlib.sha256(("\x1f".join([model, *items])).encode("utf-8")).hexdigest()
        start = time.perf_counter()
        try:
            load = getattr(embedder, "load", None)
            if load is not None:  # one-time model load, kept out of the measured latency
                load()
                start = time.perf_counter()
            vectors = embedder.encode(list(items))
        except ProviderNotConfiguredError as exc:
            self._log(task, model, lecture_id, user_id, request_hash, "not_configured", None, exc)
            raise
        except Exception as exc:  # noqa: BLE001 - model load / inference errors
            latency = (time.perf_counter() - start) * 1000
            self._log(task, model, lecture_id, user_id, request_hash, "error", latency, exc)
            raise LLMError(f"Embedding failed ({type(exc).__name__})",
                           details={"provider": PROVIDER, "model": model, "task": task}) from exc
        latency = (time.perf_counter() - start) * 1000
        self._log(task, model, lecture_id, user_id, request_hash, "ok", latency, None, n_texts=len(items))
        return vectors

    def _log(
        self,
        task: str,
        model: str,
        lecture_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        request_hash: str,
        status: str,
        latency_ms: float | None,
        error: Exception | None,
        n_texts: int | None = None,
    ) -> None:
        row = LLMCall(
            user_id=user_id,
            lecture_id=lecture_id,
            task=task,
            provider=PROVIDER,
            model=model,
            model_version=model,
            attempt=1,
            latency_ms=round(latency_ms, 2) if latency_ms is not None else None,
            cost_usd=self.pricing.cost(PROVIDER, model, None, None),
            status=status,
            error_type=(getattr(error, "error_type", None) or type(error).__name__) if error else None,
            error_message=(getattr(error, "message", None) or str(error))[:2000] if error else None,
            request_hash=request_hash,
        )
        log.info("embedding_call", task=task, model=model, status=status, latency_ms=row.latency_ms, texts=n_texts)
        save_call(self._session_factory, row)


@lru_cache
def get_embedder() -> SentenceTransformerEmbedder:
    """Process-wide singleton; the model itself loads on the first encode()."""
    from app.core.config import get_settings

    s = get_settings()
    return SentenceTransformerEmbedder(s.embedding_model, s.embedding_device)


@lru_cache
def get_embedding_client() -> EmbeddingClient:
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.services.llm.pricing import get_pricing

    return EmbeddingClient(get_settings(), get_session_factory(), get_pricing())
