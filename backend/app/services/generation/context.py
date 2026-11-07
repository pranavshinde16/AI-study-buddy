"""Transcript context for quiz and flashcard generation (Phase 6).

Both features work on the lecture's topics (from the Phase 5 notes). Each LLM request gets a
*batch*: one or more consecutive topics with their numbered transcript segments, capped at
QUIZ_CONTEXT_MAX_TOKENS so a single request fits Groq's free-tier tokens-per-minute limit.
A topic longer than the cap is split into several parts.

The model only sees segment ids like [12]; the app maps an id back to its segment (for the
timestamp) and to the topic that contains it, so topics and times are never invented.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.generation.summary import SegmentLike, _norm, estimate_text_tokens


@dataclass
class TopicSpan:
    title: str
    start_segment: int
    end_segment: int


@dataclass
class Batch:
    number: int  # 1-based
    topics: list[TopicSpan]
    segments: list[SegmentLike] = field(default_factory=list)

    @property
    def first_idx(self) -> int:
        return self.segments[0].idx

    @property
    def last_idx(self) -> int:
        return self.segments[-1].idx

    @property
    def tokens(self) -> int:
        return estimate_text_tokens(numbered(self.segments))

    @property
    def topic_titles(self) -> list[str]:
        out: list[str] = []
        for t in self.topics:
            if t.title not in out:
                out.append(t.title)
        return out

    def contains(self, segment_id: int) -> bool:
        return any(s.idx == segment_id for s in self.segments)


def numbered(segments: Sequence[SegmentLike]) -> str:
    return "\n".join(f"[{s.idx}] {s.text}" for s in segments)


def topics_from_notes(notes: dict[str, Any]) -> list[TopicSpan]:
    return [
        TopicSpan(t["title"], int(t["start_segment"]), int(t["end_segment"]))
        for t in notes.get("topics", [])
        if "start_segment" in t and "end_segment" in t
    ]


def filter_topics(topics: list[TopicSpan], wanted: Sequence[str] | None) -> tuple[list[TopicSpan], list[str]]:
    """Keep the requested topics (matched case/punctuation-insensitively). Returns (kept, unknown)."""
    if not wanted:
        return topics, []
    keys = {_norm(w): w for w in wanted}
    kept = [t for t in topics if _norm(t.title) in keys]
    found = {_norm(t.title) for t in kept}
    return kept, [w for k, w in keys.items() if k not in found]


def topic_of(topics: Sequence[TopicSpan], segment_id: int) -> str | None:
    for t in topics:
        if t.start_segment <= segment_id <= t.end_segment:
            return t.title
    return None


def build_batches(topics: Sequence[TopicSpan], segments: Sequence[SegmentLike], max_tokens: int) -> list[Batch]:
    """Pack consecutive topics into batches of at most `max_tokens` transcript tokens."""
    by_idx = {s.idx: s for s in segments if s.text.strip()}

    # 1. units: each topic's segments, split into parts that fit the cap
    units: list[tuple[TopicSpan, list[SegmentLike]]] = []
    for t in topics:
        segs = [by_idx[i] for i in range(t.start_segment, t.end_segment + 1) if i in by_idx]
        part: list[SegmentLike] = []
        tokens = 0
        for s in segs:
            n = estimate_text_tokens(f"[{s.idx}] {s.text}\n")
            if part and tokens + n > max_tokens:
                units.append((t, part))
                part, tokens = [], 0
            part.append(s)
            tokens += n
        if part:
            units.append((t, part))

    # 2. pack consecutive units
    batches: list[Batch] = []
    current: Batch | None = None
    for t, segs in units:
        if current is not None and estimate_text_tokens(numbered([*current.segments, *segs])) <= max_tokens:
            current.segments.extend(segs)
            if current.topics[-1] is not t:
                current.topics.append(t)
            continue
        current = Batch(len(batches) + 1, [t], list(segs))
        batches.append(current)
    return batches


def allocate(total: int, weights: Sequence[int]) -> list[int]:
    """Split `total` items over batches proportionally to `weights` (largest remainder).

    With fewer items than batches, the items go to batches spread evenly across the lecture."""
    n = len(weights)
    if n == 0 or total <= 0:
        return [0] * n
    if total < n:
        out = [0] * n
        for k in range(total):
            out[min(n - 1, math.floor((k + 0.5) * n / total))] += 1
        return out
    w = [max(1, x) for x in weights]
    s = sum(w)
    raw = [total * x / s for x in w]
    out = [max(1, math.floor(r)) for r in raw]
    while sum(out) > total:  # the max(1, ...) floor can overshoot
        i = max((j for j in range(n) if out[j] > 1), key=lambda j: out[j] - raw[j])
        out[i] -= 1
    order = sorted(range(n), key=lambda j: raw[j] - out[j], reverse=True)
    k = 0
    while sum(out) < total:
        out[order[k % n]] += 1
        k += 1
    return out
