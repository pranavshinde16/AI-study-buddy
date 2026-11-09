"""Small helpers shared by the eval command-line tools."""

import sys
import uuid
from datetime import datetime


def safe_console() -> None:
    """Windows consoles (cp1252) can't print every character a question may contain."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def lecture_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise SystemExit(f"--lecture-id must be a UUID, got {value!r}") from None


def stamp(msg: str) -> str:
    return f"{datetime.now().strftime('%H:%M:%S')} {msg}"
