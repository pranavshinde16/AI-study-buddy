"""Transcript export formats: plain text, SubRip (.srt) and WebVTT (.vtt).

Times come straight from the stored ASR segments (CLAUDE.md rule 3).
"""

from collections.abc import Sequence
from typing import Literal, Protocol

TranscriptFormat = Literal["txt", "srt", "vtt"]

MEDIA_TYPES: dict[str, str] = {
    "txt": "text/plain; charset=utf-8",
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
}


class SegmentLike(Protocol):
    start_sec: float
    end_sec: float
    text: str


def _clock(seconds: float, sep: str) -> str:
    """HH:MM:SS<sep>mmm, e.g. 01:02:03,456 (SRT) or 01:02:03.456 (VTT)."""
    ms_total = max(0, round(seconds * 1000))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _short(seconds: float) -> str:
    """[MM:SS] or [H:MM:SS] for the plain-text export."""
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def to_txt(segments: Sequence[SegmentLike]) -> str:
    return "".join(f"[{_short(s.start_sec)}] {s.text}\n" for s in segments)


def to_srt(segments: Sequence[SegmentLike]) -> str:
    blocks = [
        f"{i}\n{_clock(s.start_sec, ',')} --> {_clock(s.end_sec, ',')}\n{s.text}\n"
        for i, s in enumerate(segments, start=1)
    ]
    return "\n".join(blocks)


def to_vtt(segments: Sequence[SegmentLike]) -> str:
    blocks = [f"{_clock(s.start_sec, '.')} --> {_clock(s.end_sec, '.')}\n{s.text}\n" for s in segments]
    return "WEBVTT\n\n" + "\n".join(blocks)


def render(segments: Sequence[SegmentLike], fmt: TranscriptFormat) -> str:
    return {"txt": to_txt, "srt": to_srt, "vtt": to_vtt}[fmt](segments)
