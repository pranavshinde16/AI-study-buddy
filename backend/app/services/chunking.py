"""Transcript chunks for retrieval (IMPLEMENTATION_PLAN §5.2, Phase 7).

Consecutive transcript segments are grouped into windows of about CHUNK_TARGET_WORDS words
(350) that never span more than CHUNK_MAX_SEC (90 s). Each window after the first starts a few
segments back, so roughly CHUNK_OVERLAP (15 %) of its words repeat the end of the previous
window. An answer that sits on a boundary is then still found in one piece.

A chunk's `start` / `end` are the start of its first segment and the end of its last one, so
every timestamp shown for a source comes from the ASR segments (CLAUDE.md rule 3).
Segments are never split, and a single segment longer than the limits becomes its own chunk.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.generation.summary import SegmentLike


@dataclass(frozen=True)
class ChunkSpan:
    idx: int
    first_segment: int  # transcript segment idx
    last_segment: int
    start_sec: float
    end_sec: float
    text: str

    @property
    def words(self) -> int:
        return len(self.text.split())


def _words(seg: SegmentLike) -> int:
    return len(seg.text.split())


def build_chunks(
    segments: Sequence[SegmentLike], *, target_words: int = 350, max_sec: float = 90.0, overlap: float = 0.15
) -> list[ChunkSpan]:
    segs = [s for s in segments if s.text.strip()]
    out: list[ChunkSpan] = []
    i, n = 0, len(segs)
    while i < n:
        j, words = i, 0
        while j < n:
            w = _words(segs[j])
            too_many = words + w > target_words
            too_long = segs[j].end_sec - segs[i].start_sec > max_sec
            if j > i and (too_many or too_long):
                break
            words += w
            j += 1
        window = segs[i:j]
        out.append(
            ChunkSpan(
                idx=len(out),
                first_segment=window[0].idx,
                last_segment=window[-1].idx,
                start_sec=window[0].start_sec,
                end_sec=window[-1].end_sec,
                text=" ".join(s.text.strip() for s in window),
            )
        )
        if j >= n:
            break
        # Start the next window a few segments back (~overlap of this window's words),
        # but always move forward by at least one segment.
        k, back = j, 0
        while k - 1 > i and back + _words(segs[k - 1]) <= overlap * words:
            k -= 1
            back += _words(segs[k])
        i = max(k, i + 1)
    return out
