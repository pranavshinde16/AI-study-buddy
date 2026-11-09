"""Golden-set files: backend/eval/golden/<name>.jsonl, one hand-written question per line.

    {"id", "question", "answerable", "gold_start", "gold_end", "reference_answer", "kind"}

The labels are written by the team, never generated (IMPLEMENTATION_PLAN §7.3). This module
only reads and validates them.
"""

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

GOLDEN_DIR = Path(__file__).resolve().parents[3] / "eval" / "golden"
SET_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")

Kind = Literal["on_topic", "near_topic", "off_topic"]


class GoldenItem(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1)
    answerable: bool
    gold_start: float | None = Field(None, ge=0)
    gold_end: float | None = Field(None, ge=0)
    reference_answer: str | None = None
    kind: Kind
    difficulty: str | None = Field(None, max_length=32)  # optional label (e.g. Easy / Medium / Hard), reporting only

    @model_validator(mode="after")
    def _consistent(self) -> "GoldenItem":
        if self.answerable:
            if self.gold_start is None or self.gold_end is None:
                raise ValueError("answerable questions need gold_start and gold_end")
            if self.gold_end < self.gold_start:
                raise ValueError("gold_end is before gold_start")
            if not (self.reference_answer or "").strip():
                raise ValueError("answerable questions need a reference_answer")
        if (self.gold_start is None) != (self.gold_end is None):
            raise ValueError("give both gold_start and gold_end, or neither")
        return self


class GoldenSetError(ValueError):
    def __init__(self, message: str, problems: list[str]) -> None:
        super().__init__(message)
        self.problems = problems


def golden_path(name: str, directory: Path = GOLDEN_DIR) -> Path:
    if not SET_NAME.match(name):
        raise GoldenSetError(f"Invalid set name {name!r}", [f"use letters, digits, '_', '-', '.' only"])
    return directory / f"{name}.jsonl"


def parse_golden(text: str, *, duration_sec: float | None = None) -> tuple[list[GoldenItem], list[str], list[str]]:
    """Returns (items, problems, warnings). Problems make the set unusable; warnings don't."""
    items: list[GoldenItem] = []
    problems: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"line {n}: not valid JSON ({exc.msg})")
            continue
        try:
            item = GoldenItem.model_validate(raw)
        except ValidationError as exc:
            msgs = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'item'}: {e['msg']}" for e in exc.errors())
            problems.append(f"line {n}: {msgs}")
            continue
        if item.id in seen:
            problems.append(f"line {n}: duplicate id {item.id!r}")
            continue
        seen.add(item.id)
        extra = set(raw) - set(GoldenItem.model_fields)
        if extra:
            warnings.append(f"line {n} ({item.id}): unknown fields ignored: {sorted(extra)}")
        if item.answerable and item.kind != "on_topic":
            warnings.append(f"line {n} ({item.id}): answerable but kind={item.kind}")
        if not item.answerable and item.kind == "on_topic":
            warnings.append(f"line {n} ({item.id}): not answerable but kind=on_topic")
        if duration_sec is not None and item.gold_end is not None and item.gold_end > duration_sec + 1:
            problems.append(f"line {n} ({item.id}): gold_end {item.gold_end} is after the lecture's end "
                            f"({duration_sec:.1f} s)")
        items.append(item)
    if not items and not problems:
        problems.append("the file has no questions yet")
    return items, problems, warnings


def load_golden(name: str, *, duration_sec: float | None = None,
                directory: Path = GOLDEN_DIR) -> tuple[list[GoldenItem], list[str]]:
    """Load and validate; raises GoldenSetError with every problem. Returns (items, warnings)."""
    path = golden_path(name, directory)
    if not path.is_file():
        raise GoldenSetError(f"Golden set not found: {path}", [f"create {path.name} in {directory}"])
    items, problems, warnings = parse_golden(path.read_text(encoding="utf-8-sig"), duration_sec=duration_sec)
    if problems:
        raise GoldenSetError(f"{path.name} has {len(problems)} problem(s)", problems)
    return items, warnings
