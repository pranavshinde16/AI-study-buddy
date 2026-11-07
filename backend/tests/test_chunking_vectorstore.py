"""Chunking (word/time windows with overlap, times from segments) and the Chroma vector store
(cosine space, score = 1 - distance, lecture filter, delete, persistence). No network."""

import math
import uuid
from dataclasses import dataclass

import pytest

from app.services.chunking import build_chunks
from app.services.vectorstore import ChromaVectorStore, VectorItem, item_id


@dataclass
class Seg:
    idx: int
    start_sec: float
    end_sec: float
    text: str


def segs(n: int, words: int = 10, dur: float = 5.0) -> list[Seg]:
    return [Seg(i, i * dur, i * dur + dur - 0.5, " ".join(f"w{i}_{k}" for k in range(words))) for i in range(n)]


# ---------------------------------------------------------------------------- chunking


def test_chunks_respect_word_and_time_limits_and_keep_segment_times():
    s = segs(100)  # 10 words / 5 s each
    chunks = build_chunks(s, target_words=100, max_sec=90, overlap=0.15)
    assert len(chunks) > 5
    for c in chunks:
        assert c.words <= 100
        assert c.end_sec - c.start_sec <= 90
        assert c.start_sec == s[c.first_segment].start_sec and c.end_sec == s[c.last_segment].end_sec
    assert chunks[0].first_segment == 0 and chunks[-1].last_segment == 99  # whole transcript covered
    assert [c.idx for c in chunks] == list(range(len(chunks)))


def test_chunks_overlap_about_fifteen_percent():
    chunks = build_chunks(segs(100), target_words=100, max_sec=1000, overlap=0.15)
    for a, b in zip(chunks, chunks[1:]):
        shared = a.last_segment - b.first_segment + 1
        assert shared == 1  # 15% of 100 words = 15 -> one 10-word segment repeats
        assert b.first_segment > a.first_segment


def test_time_limit_cuts_before_word_limit():
    chunks = build_chunks(segs(40, words=2, dur=10.0), target_words=350, max_sec=90, overlap=0.0)
    assert all(c.end_sec - c.start_sec <= 90 for c in chunks)
    assert chunks[0].last_segment == 8  # 9 segments x 10 s = 89.5 s


def test_long_single_segment_and_empty_input():
    long = [Seg(0, 0.0, 300.0, "word " * 1000)]
    chunks = build_chunks(long, target_words=350, max_sec=90)
    assert len(chunks) == 1 and chunks[0].end_sec == 300.0  # never split a segment
    assert build_chunks([], target_words=350) == []
    assert build_chunks([Seg(0, 0, 1, "  ")]) == []


# ---------------------------------------------------------------------------- vector store


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def test_cosine_space_score_is_one_minus_distance(vector_store):
    lid, other = uuid.uuid4(), uuid.uuid4()
    a, b, c = _norm([1, 0, 0]), _norm([1, 1, 0]), _norm([0, 0, 1])
    vector_store.upsert(lid, [VectorItem(item_id(lid, 0), a, "alpha", {"idx": 0, "start": 0.0, "end": 5.0}),
                              VectorItem(item_id(lid, 1), b, "beta", {"idx": 1, "start": 5.0, "end": 9.0})])
    vector_store.upsert(other, [VectorItem(item_id(other, 0), a, "other lecture", {"idx": 0, "start": 0, "end": 1})])

    assert vector_store._col().metadata["hnsw:space"] == "cosine"
    hits = vector_store.query(lid, a, k=5)
    assert [h.text for h in hits] == ["alpha", "beta"]  # filtered to this lecture only
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)
    assert hits[1].score == pytest.approx(1 / math.sqrt(2), abs=1e-4)  # = cosine similarity
    assert hits[0].metadata["lecture_id"] == str(lid) and hits[0].metadata["start"] == 0.0
    assert vector_store.query(lid, c, k=1)[0].score == pytest.approx(0.0, abs=1e-5)

    assert vector_store.count(lid) == 2 and vector_store.count(other) == 1
    vector_store.delete_lecture(lid)
    assert vector_store.count(lid) == 0 and vector_store.count(other) == 1
    assert vector_store.heartbeat() is True


def test_persistent_store_survives_reopening(tmp_path):
    lid = uuid.uuid4()
    first = ChromaVectorStore(path=str(tmp_path / "chroma"), collection="persist_test")
    first.upsert(lid, [VectorItem(item_id(lid, 0), _norm([1, 2, 3]), "kept", {"idx": 0, "start": 1.0, "end": 2.0})])
    again = ChromaVectorStore(path=str(tmp_path / "chroma"), collection="persist_test")
    assert again.count(lid) == 1 and again.query(lid, _norm([1, 2, 3]), 1)[0].text == "kept"


def test_collection_name_includes_environment(settings):
    from app.services.vectorstore import collection_name

    assert collection_name(settings) == "lecture_chunks_test"
