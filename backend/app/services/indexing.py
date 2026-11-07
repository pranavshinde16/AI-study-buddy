"""Indexing a lecture for retrieval (IMPLEMENTATION_PLAN §5.3, Phase 7).

    chunks = build_chunks(segments)               # services/chunking.py
    vectors = embeddings.embed(chunk texts)       # stored text: NO query prefix
    vector store upsert (metadata: lecture_id, idx, start, end, embedding_model)
    `chunks` table rows (idx, start_sec, end_sec, text, vector_id)

The pipeline indexes right after transcription. Lectures transcribed before Phase 7 (or whose
vectors were lost, or that were indexed with another embedding model) are indexed on their
first question instead: `ensure_indexed()` compares the `chunks` rows with what is in the
vector store and re-indexes when they disagree. A per-lecture lock stops two requests from
indexing the same lecture at once.
"""

import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.lecture import Chunk, TranscriptSegment
from app.services.chunking import build_chunks
from app.services.embeddings import EmbeddingClient
from app.services.vectorstore import VectorItem, VectorStore, item_id

log = structlog.get_logger(__name__)

_locks: dict[uuid.UUID, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _lock_for(lecture_id: uuid.UUID) -> threading.Lock:
    with _locks_guard:
        return _locks[lecture_id]


@dataclass
class IndexResult:
    chunks: int
    duration_ms: float
    indexed_now: bool


class LectureIndexer:
    def __init__(self, settings: Settings, embeddings: EmbeddingClient, store: VectorStore) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self.store = store

    @property
    def model_name(self) -> str:
        return self.embeddings.embedder.model_name

    def index(self, db: Session, lecture_id: uuid.UUID, user_id: uuid.UUID | None) -> IndexResult:
        """(Re)build the lecture's chunks and vectors. Commits the chunk rows."""
        with _lock_for(lecture_id):
            return self._index(db, lecture_id, user_id)

    def ensure_indexed(self, db: Session, lecture_id: uuid.UUID, user_id: uuid.UUID | None) -> IndexResult:
        """Index only if the stored chunks and the vector store don't match."""
        with _lock_for(lecture_id):
            rows = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.lecture_id == lecture_id)) or 0
            if rows and self.store.count(lecture_id, {"embedding_model": self.model_name}) == rows:
                return IndexResult(rows, 0.0, False)
            log.info("lecture_index_missing", lecture_id=str(lecture_id), chunk_rows=rows)
            return self._index(db, lecture_id, user_id)

    def _index(self, db: Session, lecture_id: uuid.UUID, user_id: uuid.UUID | None) -> IndexResult:
        t0 = time.perf_counter()
        segments = list(
            db.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.lecture_id == lecture_id)
                .order_by(TranscriptSegment.idx)
            )
        )
        spans = build_chunks(
            segments,
            target_words=self.settings.chunk_target_words,
            max_sec=self.settings.chunk_max_sec,
            overlap=self.settings.chunk_overlap,
        )
        vectors = (
            self.embeddings.embed([c.text for c in spans], task="rag_index", lecture_id=lecture_id, user_id=user_id)
            if spans
            else []
        )
        model = self.model_name
        self.store.delete_lecture(lecture_id)
        self.store.upsert(
            lecture_id,
            [
                VectorItem(
                    id=item_id(lecture_id, c.idx),
                    vector=v,
                    text=c.text,
                    metadata={"idx": c.idx, "start": c.start_sec, "end": c.end_sec,
                              "first_segment": c.first_segment, "last_segment": c.last_segment,
                              "embedding_model": model},
                )
                for c, v in zip(spans, vectors)
            ],
        )
        db.execute(delete(Chunk).where(Chunk.lecture_id == lecture_id))
        db.add_all(
            Chunk(lecture_id=lecture_id, idx=c.idx, start_sec=c.start_sec, end_sec=c.end_sec, text=c.text,
                  vector_id=item_id(lecture_id, c.idx))
            for c in spans
        )
        db.commit()
        ms = round((time.perf_counter() - t0) * 1000, 1)
        log.info("lecture_indexed", lecture_id=str(lecture_id), chunks=len(spans), duration_ms=ms)
        return IndexResult(len(spans), ms, True)

    def remove(self, lecture_id: uuid.UUID) -> None:
        """Delete the lecture's vectors (the chunk rows go with the lecture via CASCADE).
        Best effort: a vector-store problem must not block deleting the lecture."""
        try:
            self.store.delete_lecture(lecture_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("vector_delete_failed", lecture_id=str(lecture_id), error_type=type(exc).__name__)


@lru_cache
def get_indexer() -> LectureIndexer:
    from app.core.config import get_settings
    from app.services.embeddings import get_embedding_client
    from app.services.vectorstore import get_vector_store

    return LectureIndexer(get_settings(), get_embedding_client(), get_vector_store())
