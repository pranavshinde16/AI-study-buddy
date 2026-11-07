"""Generate short test media with ffmpeg (a sine tone; no recordings are committed).

Tests that need these are skipped when ffmpeg/ffprobe are not installed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args], check=True)


def make_tone(path: Path, seconds: float = 5.0) -> Path:
    """A 440 Hz tone. The container/codec follows the extension: .wav, .mp3, .m4a, .flac."""
    path.parent.mkdir(parents=True, exist_ok=True)
    codec = {".mp3": ["-c:a", "libmp3lame"], ".m4a": ["-c:a", "aac"]}.get(path.suffix, [])
    _ffmpeg("-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", *codec, str(path))
    return path


def make_video(path: Path, seconds: float = 5.0, *, with_audio: bool = True) -> Path:
    """A tiny black MP4 (mpeg4 video, built into every ffmpeg) with or without an AAC tone."""
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["-f", "lavfi", "-i", f"color=c=black:s=64x64:d={seconds}"]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    _ffmpeg(*args, "-c:v", "mpeg4", str(path))
    return path
