"""Vector store for transcript chunks (IMPLEMENTATION_PLAN §5.2, Phase 7).

ChromaDB, persistent on disk at CHROMA_DIR. There is one collection per app environment
(`lecture_chunks_development`, `lecture_chunks_test`, ...), so dev and test vectors never mix.

- The collection uses cosine distance (`{"hnsw:space": "cosine"}`), and the store reports
  score = 1 - distance, which for our normalised vectors is the cosine similarity (-1..1).
- Every item has `lecture_id` metadata, and queries are always filtered by it.
- The app computes the embeddings itself (services/embeddings.py) and passes them in:
  `embedding_function=None`, so Chroma never downloads or runs a model of its own.
- Telemetry is off (`anonymized_telemetry=False`): no network traffic.

Item ids are "<lecture_id>:<chunk idx>".
"""

import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)


@dataclass
class VectorItem:
    id: str
    vector: list[float]
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hit:
    id: str
    score: float  # 1 - cosine distance
    text: str
    metadata: dict[str, Any]


class VectorStore(Protocol):
    def upsert(self, lecture_id: uuid.UUID, items: Sequence[VectorItem]) -> None: ...
    def query(self, lecture_id: uuid.UUID, vector: list[float], k: int) -> list[Hit]: ...
    def delete_lecture(self, lecture_id: uuid.UUID) -> None: ...
    def count(self, lecture_id: uuid.UUID, where: dict[str, Any] | None = None) -> int: ...
    def heartbeat(self) -> bool: ...


def item_id(lecture_id: uuid.UUID, idx: int) -> str:
    return f"{lecture_id}:{idx}"


class ChromaVectorStore:
    def __init__(self, *, path: str | None = None, collection: str, client: Any = None) -> None:
        """Pass `path` for a persistent store, or a ready `client` (tests use an in-memory one)."""
        self._path = path
        self._client = client
        self._collection_name = collection
        self._collection = None
        self._lock = threading.Lock()

    def _col(self):
        if self._collection is None:
            with self._lock:
                if self._collection is None:
                    import chromadb
                    from chromadb.config import Settings as ChromaSettings

                    if self._client is None:
                        self._client = chromadb.PersistentClient(
                            path=self._path, settings=ChromaSettings(anonymized_telemetry=False)
                        )
                    self._collection = self._client.get_or_create_collection(
                        self._collection_name, metadata={"hnsw:space": "cosine"}, embedding_function=None
                    )
        return self._collection

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def upsert(self, lecture_id: uuid.UUID, items: Sequence[VectorItem]) -> None:
        if not items:
            return
        self._col().upsert(
            ids=[i.id for i in items],
            embeddings=[i.vector for i in items],
            documents=[i.text for i in items],
            metadatas=[{**i.metadata, "lecture_id": str(lecture_id)} for i in items],
        )

    def query(self, lecture_id: uuid.UUID, vector: list[float], k: int) -> list[Hit]:
        col = self._col()
        res = col.query(
            query_embeddings=[vector],
            n_results=max(1, k),
            where={"lecture_id": str(lecture_id)},
            include=["distances", "documents", "metadatas"],
        )
        ids = res["ids"][0] if res["ids"] else []
        return [
            Hit(id=i, score=round(1.0 - float(d), 6), text=doc or "", metadata=dict(meta or {}))
            for i, d, doc, meta in zip(ids, res["distances"][0], res["documents"][0], res["metadatas"][0])
        ]

    def delete_lecture(self, lecture_id: uuid.UUID) -> None:
        self._col().delete(where={"lecture_id": str(lecture_id)})

    def count(self, lecture_id: uuid.UUID, where: dict[str, Any] | None = None) -> int:
        clause: dict[str, Any] = {"lecture_id": str(lecture_id)}
        if where:
            clause = {"$and": [clause, *({k: v} for k, v in where.items())]}
        return len(self._col().get(where=clause, include=[])["ids"])

    def heartbeat(self) -> bool:
        try:
            self._col().count()
            return True
        except Exception as exc:  # noqa: BLE001 - reported by /health
            log.warning("vector_store_unavailable", error_type=type(exc).__name__)
            return False


def collection_name(settings: Settings) -> str:
    return f"{settings.chroma_collection}_{settings.app_env}"


@lru_cache
def get_vector_store() -> ChromaVectorStore:
    from app.core.config import get_settings

    s = get_settings()
    return ChromaVectorStore(path=str(s.chroma_path), collection=collection_name(s))
