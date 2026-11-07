"""Summary, topics and topic notes for one lecture (IMPLEMENTATION_PLAN §5.2, Phase 5).

Flow (all calls go through the logged LLM client):

    1. windows  : the transcript is one window if it is short (<= SUMMARY_SINGLE_PASS_MAX_TOKENS),
                  else ~10-minute windows capped at SUMMARY_WINDOW_MAX_TOKENS (map-reduce).
    2. topics   : MAP, one `topics` call per window -> topics as segment-id ranges + definitions.
    3. notes    : one `notes` call per topic, using only that topic's segments.
    4. summary  : REDUCE, one `summary` call over the full transcript (short lecture) or over
                  the topics' key points (long lecture).

Grounding: the model only ever sees segment ids such as [12], never asked for times. Every
timestamp in the result is looked up from the stored transcript segments; ids outside the
window are clamped to it, and a definition whose id is invalid gets no timestamp (never a guess).
"""

import bisect
import math
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol

from fastapi import status
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import AppError
from app.services.llm.client import LLMClient, LLMResult
from app.services.llm.ratelimit import CHARS_PER_TOKEN

ProgressFn = Callable[[str, float], None]  # (stage detail, fraction 0..1)


class SegmentLike(Protocol):
    idx: int
    start_sec: float
    end_sec: float
    text: str


class TranscriptEmptyError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "TRANSCRIPT_EMPTY"


# ---------------------------------------------------------------------------- LLM output schemas


class TopicItem(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_segment: int = Field(description="id of the first transcript segment of this topic")
    end_segment: int = Field(description="id of the last transcript segment of this topic")
    key_points: list[str] = Field(default_factory=list, description="2-5 short statements from the lecture")


class DefinitionItem(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1)
    segment_id: int = Field(description="id of the segment where the lecturer explains the term")


class TopicsOut(BaseModel):
    topics: list[TopicItem] = Field(min_length=1)
    definitions: list[DefinitionItem] = Field(default_factory=list)


class NotesOut(BaseModel):
    notes_md: str = Field(min_length=1)


class SummaryOut(BaseModel):
    summary: str = Field(min_length=1)
    key_takeaways: list[str] = Field(min_length=1)
    revision_notes_md: str = Field(min_length=1)


# ---------------------------------------------------------------------------- windows


def estimate_text_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def numbered_lines(segments: Sequence[SegmentLike]) -> str:
    return "\n".join(f"[{s.idx}] {s.text}" for s in segments)


def plain_text(segments: Sequence[SegmentLike]) -> str:
    return " ".join(s.text for s in segments)


@dataclass
class Window:
    number: int  # 1-based
    segments: list[SegmentLike]

    @property
    def first_idx(self) -> int:
        return self.segments[0].idx

    @property
    def last_idx(self) -> int:
        return self.segments[-1].idx

    @property
    def duration_sec(self) -> float:
        return self.segments[-1].end_sec - self.segments[0].start_sec


def build_windows(
    segments: Sequence[SegmentLike], *, window_sec: int, window_max_tokens: int, single_pass_max_tokens: int
) -> list[Window]:
    """One window for a short transcript; otherwise ~window_sec pieces that never exceed
    window_max_tokens (a window always holds at least one segment)."""
    segs = list(segments)
    if not segs:
        return []
    if estimate_text_tokens(numbered_lines(segs)) <= single_pass_max_tokens:
        return [Window(1, segs)]

    groups: list[list[SegmentLike]] = []
    current: list[SegmentLike] = []
    tokens = 0
    for seg in segs:
        seg_tokens = estimate_text_tokens(f"[{seg.idx}] {seg.text}\n")
        too_long = current and (seg.end_sec - current[0].start_sec > window_sec)
        too_big = current and (tokens + seg_tokens > window_max_tokens)
        if too_long or too_big:
            groups.append(current)
            current, tokens = [], 0
        current.append(seg)
        tokens += seg_tokens
    if current:
        # Fold a short tail (< 25% of a window) into the previous window when it still fits.
        if groups and (current[-1].end_sec - current[0].start_sec) < 0.25 * window_sec:
            merged = groups[-1] + current
            if estimate_text_tokens(numbered_lines(merged)) <= window_max_tokens:
                groups[-1] = merged
                current = []
        if current:
            groups.append(current)
    return [Window(i + 1, g) for i, g in enumerate(groups)]


def max_topics_for(window: Window) -> int:
    """About one topic per 3 minutes, between 1 and 6."""
    return max(1, min(6, math.ceil(window.duration_sec / 180)))


# ---------------------------------------------------------------------------- grounding helpers


@dataclass
class Topic:
    title: str
    start_segment: int
    end_segment: int
    key_points: list[str] = field(default_factory=list)
    notes_md: str = ""


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def resolve_topics(raw: Sequence[TopicItem], window: Window) -> list[Topic]:
    """Clamp ids into the window, order them, remove overlaps and close gaps so the topics
    cover the window contiguously. The output depends only on real segment ids."""
    lo, hi = window.first_idx, window.last_idx
    items: list[Topic] = []
    for t in raw:
        s, e = _clamp(t.start_segment, lo, hi), _clamp(t.end_segment, lo, hi)
        if s > e:
            s, e = e, s
        items.append(Topic(t.title.strip(), s, e, [p.strip() for p in t.key_points if p.strip()][:6]))
    items.sort(key=lambda t: (t.start_segment, t.end_segment))

    out: list[Topic] = []
    for t in items:
        if out and t.start_segment <= out[-1].end_segment:
            t.start_segment = out[-1].end_segment + 1
            if t.start_segment > t.end_segment:  # fully inside the previous topic
                out[-1].key_points.extend(t.key_points)
                continue
        out.append(t)
    if not out:
        return [Topic(f"Part {window.number}", lo, hi)]
    out[0].start_segment = lo
    for prev, nxt in zip(out, out[1:]):
        prev.end_segment = nxt.start_segment - 1
    out[-1].end_segment = hi
    return out


def merge_adjacent(topics: list[Topic]) -> list[Topic]:
    """Join neighbouring topics with the same title (a topic that crossed a window boundary)."""
    out: list[Topic] = []
    for t in topics:
        if out and _norm(out[-1].title) == _norm(t.title):
            out[-1].end_segment = t.end_segment
            out[-1].key_points.extend(t.key_points)
        else:
            out.append(t)
    return out


def _at_or_after(ids: list[int], idx: int) -> int:
    """The first real segment id >= idx (or the last one)."""
    i = bisect.bisect_left(ids, idx)
    return ids[min(i, len(ids) - 1)]


def _at_or_before(ids: list[int], idx: int) -> int:
    """The last real segment id <= idx (or the first one)."""
    i = bisect.bisect_right(ids, idx) - 1
    return ids[max(i, 0)]


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s).strip().lower()


# ---------------------------------------------------------------------------- generator


@dataclass
class GenerationResult:
    summary: dict[str, Any]  # stored in lecture_outputs (kind=summary)
    notes: dict[str, Any]  # stored in lecture_outputs (kind=notes)
    model: str
    summary_prompt: str
    notes_prompt: str


@dataclass
class _Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    prompts: dict[str, str] = field(default_factory=dict)

    def add(self, r: LLMResult) -> None:
        self.calls += len(r.call_ids) or 1
        self.input_tokens += r.input_tokens
        self.output_tokens += r.output_tokens
        self.latency_ms += r.latency_ms
        self.provider, self.model = r.provider, r.model
        self.model_version = r.model_version or self.model_version
        self.prompts[r.prompt_id] = r.prompt_version


class LectureGenerator:
    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self.settings = settings
        self.llm = llm

    def generate(
        self,
        *,
        lecture_id: uuid.UUID,
        user_id: uuid.UUID | None,
        title: str,
        segments: Sequence[SegmentLike],
        on_progress: ProgressFn | None = None,
    ) -> GenerationResult:
        segs = [s for s in segments if s.text.strip()]
        if not segs:
            raise TranscriptEmptyError("The transcript is empty (no speech was recognised), so there is nothing to summarise.")
        by_idx = {s.idx: s for s in segs}
        progress = on_progress or (lambda _d, _f: None)
        usage = _Usage()
        call = dict(lecture_id=lecture_id, user_id=user_id)

        windows = build_windows(
            segs,
            window_sec=self.settings.summary_window_sec,
            window_max_tokens=self.settings.summary_window_max_tokens,
            single_pass_max_tokens=self.settings.summary_single_pass_max_tokens,
        )
        mode = "single_pass" if len(windows) == 1 else "map_reduce"

        # 1-2. MAP: topics + definitions per window
        topics: list[Topic] = []
        definitions: list[dict[str, Any]] = []
        seen_terms: set[str] = set()
        for w in windows:
            progress(f"topics {w.number} of {len(windows)}", 0.05 + 0.35 * (w.number - 1) / len(windows))
            r = self.llm.complete(
                task="topics",
                prompt_id="topics",
                schema=TopicsOut,
                variables={
                    "title": title,
                    "window_number": w.number,
                    "window_count": len(windows),
                    "first_segment": w.first_idx,
                    "last_segment": w.last_idx,
                    "max_topics": max_topics_for(w),
                    "transcript": numbered_lines(w.segments),
                },
                **call,
            )
            usage.add(r)
            out: TopicsOut = r.data  # type: ignore[assignment]
            topics.extend(resolve_topics(out.topics, w))
            for d in out.definitions:
                key = _norm(d.term)
                if not key or key in seen_terms:
                    continue
                seen_terms.add(key)
                seg = by_idx.get(d.segment_id) if w.first_idx <= d.segment_id <= w.last_idx else None
                definitions.append(
                    {
                        "term": d.term.strip(),
                        "definition": d.definition.strip(),
                        "timestamp": seg.start_sec if seg else None,
                        "segment_id": seg.idx if seg else None,
                    }
                )
        topics = merge_adjacent(topics)

        # 3. notes per topic (only that topic's segments)
        for i, t in enumerate(topics):
            progress(f"notes {i + 1} of {len(topics)}", 0.4 + 0.45 * i / len(topics))
            topic_segs = [by_idx[k] for k in range(t.start_segment, t.end_segment + 1) if k in by_idx]
            r = self.llm.complete(
                task="notes",
                prompt_id="notes",
                schema=NotesOut,
                variables={"title": title, "topic_title": t.title, "transcript": plain_text(topic_segs)},
                **call,
            )
            usage.add(r)
            t.notes_md = r.data.notes_md.strip()  # type: ignore[union-attr]

        # 4. REDUCE: summary
        progress("summary", 0.9)
        if mode == "single_pass":
            source_kind, source = "full lecture transcript", plain_text(segs)
        else:
            source_kind = "topics and key points extracted from the transcript, in lecture order"
            source = "\n\n".join(
                f"## {t.title}\n" + "\n".join(f"- {p}" for p in t.key_points) for t in topics
            )
        r = self.llm.complete(
            task="summary",
            prompt_id="summary",
            schema=SummaryOut,
            variables={"title": title, "source_kind": source_kind, "source": source},
            **call,
        )
        usage.add(r)
        s: SummaryOut = r.data  # type: ignore[assignment]

        meta = {
            "provider": usage.provider,
            "model": usage.model,
            "model_version": usage.model_version,
            "prompt_version": usage.prompts.get("summary"),
            "prompt_versions": dict(usage.prompts),
            "mode": mode,
            "windows": len(windows),
            "llm_calls": usage.calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "llm_latency_ms": round(usage.latency_ms, 1),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        ids = sorted(by_idx)
        topic_dicts = [
            {
                "title": t.title,
                "start": by_idx[_at_or_after(ids, t.start_segment)].start_sec,
                "end": by_idx[_at_or_before(ids, t.end_segment)].end_sec,
                "start_segment": t.start_segment,
                "end_segment": t.end_segment,
                "key_points": t.key_points,
                "notes_md": t.notes_md,
            }
            for t in topics
        ]
        progress("saving", 1.0)
        return GenerationResult(
            summary={
                "summary": s.summary.strip(),
                "key_takeaways": [k.strip() for k in s.key_takeaways if k.strip()],
                "definitions": definitions,
                "revision_notes_md": s.revision_notes_md.strip(),
                "meta": meta,
            },
            notes={"topics": topic_dicts, "meta": meta},
            model=usage.model or "",
            summary_prompt=usage.prompts.get("summary", ""),
            notes_prompt=usage.prompts.get("notes", usage.prompts.get("topics", "")),
        )


@lru_cache
def get_lecture_generator() -> LectureGenerator:
    from app.core.config import get_settings
    from app.services.llm.client import get_llm_client

    return LectureGenerator(get_settings(), get_llm_client())
