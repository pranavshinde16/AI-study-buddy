"""Audio handling with ffmpeg / ffprobe (IMPLEMENTATION_PLAN §5.2).

- `probe()`         duration and whether the file has an audio stream
- `extract_chunks()` convert to 16 kHz mono FLAC and cut it into pieces of about ASR_CHUNK_SEC,
                     each small enough for Groq's 25 MB limit, with its exact start offset

ffmpeg runs as a subprocess with a list of arguments (no shell) and a timeout.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import status

from app.core.errors import AppError

if TYPE_CHECKING:
    from app.core.config import Settings


class MediaError(AppError):
    """The file could not be read or converted (bad/corrupt media, or ffmpeg missing)."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "MEDIA_ERROR"


class UnsupportedMediaError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "UNSUPPORTED_MEDIA_TYPE"


@dataclass(frozen=True)
class ProbeResult:
    duration_sec: float
    has_audio: bool
    format_name: str


@dataclass(frozen=True)
class AudioChunk:
    index: int
    path: Path
    offset_sec: float  # where this piece starts in the original lecture
    duration_sec: float
    size_bytes: int


class Media:
    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe", timeout_sec: int = 1800) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.timeout_sec = timeout_sec

    # ------------------------------------------------------------------ helpers

    def _run(self, args: list[str], what: str) -> subprocess.CompletedProcess[str]:
        exe = args[0]
        if shutil.which(exe) is None and not Path(exe).is_file():
            raise MediaError(
                f"{exe} was not found. Install ffmpeg and make sure it is on PATH (see README, Prerequisites).",
                code="FFMPEG_NOT_FOUND",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            return subprocess.run(
                args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout_sec, check=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaError(f"{what} took longer than {self.timeout_sec} s and was stopped") from exc
        except subprocess.CalledProcessError as exc:
            tail = (exc.stderr or "").strip().splitlines()[-3:]
            raise MediaError(f"{what} failed", details={"ffmpeg": " | ".join(tail)[:500]}) from exc

    # ------------------------------------------------------------------ public

    def probe(self, path: Path) -> ProbeResult:
        """Read duration and stream types. Raises UnsupportedMediaError for non-media or video without audio."""
        try:
            proc = self._run(
                [self.ffprobe_bin, "-v", "error", "-show_entries", "format=duration,format_name:stream=codec_type",
                 "-of", "json", str(path)],
                "Reading the media file",
            )
        except MediaError as exc:
            if exc.code == "FFMPEG_NOT_FOUND":
                raise
            raise UnsupportedMediaError("The file is not a readable audio or video file") from exc
        info = json.loads(proc.stdout or "{}")
        has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        fmt = info.get("format", {})
        try:
            duration = float(fmt.get("duration"))
        except (TypeError, ValueError):
            duration = 0.0
        if not has_audio:
            raise UnsupportedMediaError("The file has no audio track")
        if duration <= 0:
            raise UnsupportedMediaError("Could not read the file's duration")
        return ProbeResult(duration_sec=duration, has_audio=True, format_name=str(fmt.get("format_name", "")))

    def extract_chunks(self, src: Path, out_dir: Path, chunk_sec: int, max_chunk_bytes: int) -> list[AudioChunk]:
        """Convert to 16 kHz mono FLAC, then cut it into pieces of about `chunk_sec` seconds.

        Each piece is cut from the converted file at an exact start time, and that start time is
        its offset, so timestamps stay continuous across pieces. A piece larger than
        `max_chunk_bytes` (Groq's upload limit) is cut again into halves.
        """
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        full = out_dir / "full.flac"
        self._run(
            [self.ffmpeg_bin, "-hide_banner", "-nostdin", "-y", "-i", str(src),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(full)],
            "Extracting audio",
        )
        total = self._duration(full)
        if total <= 0:
            raise MediaError("No audio could be extracted from the file")

        chunks: list[AudioChunk] = []
        start = 0.0
        while start < total - 0.05:  # ignore a trailing sliver under 50 ms
            length = min(float(chunk_sec), total - start)
            for offset, dur, path in self._cut_fitting(full, out_dir, start, length, max_chunk_bytes):
                chunks.append(AudioChunk(len(chunks), path, round(offset, 3), round(dur, 3), path.stat().st_size))
            start += length
        full.unlink(missing_ok=True)
        # Number the files in timeline order (halves were cut with temporary names).
        for c in chunks:
            final = out_dir / f"chunk_{c.index:03d}.flac"
            c.path.rename(final)
        return [AudioChunk(c.index, out_dir / f"chunk_{c.index:03d}.flac", c.offset_sec, c.duration_sec, c.size_bytes)
                for c in chunks]

    def _cut(self, full: Path, dest: Path, start: float, length: float) -> None:
        self._run(
            [self.ffmpeg_bin, "-hide_banner", "-nostdin", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
             "-i", str(full), "-c:a", "flac", str(dest)],
            "Cutting audio",
        )

    def _cut_fitting(
        self, full: Path, out_dir: Path, start: float, length: float, max_bytes: int
    ) -> list[tuple[float, float, Path]]:
        """Cut [start, start+length); if the file is too big, cut the two halves instead (recursively)."""
        dest = out_dir / f"tmp_{start:012.3f}_{length:09.3f}.flac"
        self._cut(full, dest, start, length)
        if dest.stat().st_size <= max_bytes or length <= 30:
            return [(start, length, dest)]
        dest.unlink()
        half = length / 2
        return [
            *self._cut_fitting(full, out_dir, start, half, max_bytes),
            *self._cut_fitting(full, out_dir, start + half, length - half, max_bytes),
        ]

    def _duration(self, path: Path) -> float:
        proc = self._run(
            [self.ffprobe_bin, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            "Measuring an audio chunk",
        )
        return round(float(json.loads(proc.stdout)["format"]["duration"]), 3)


def media_from_settings(settings: "Settings") -> Media:
    return Media(settings.ffmpeg_bin, settings.ffprobe_bin, settings.media_timeout_sec)
