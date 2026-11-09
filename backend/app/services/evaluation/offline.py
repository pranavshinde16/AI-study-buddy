"""Import the Phase 10 SciQ evaluation files as "offline" eval runs, so the LLMOps page shows
the base-vs-fine-tuned SciQ results next to the lecture golden-set results.

    finetune/results/eval_hf.json               -> golden_set "sciq_test_500"       (Colab T4, HF backend)
    finetune/results/eval_ollama_subset50.json  -> golden_set "sciq_test_subset50"  (CPU, Ollama backend)

One eval_runs row per model in the file (base, finetuned). metrics_json is the file's own
per-model summary, copied unchanged; nothing is recomputed. Importing the same file twice is
a no-op (matched on file name + created_at + items fingerprint).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.llmops import EvalRun

OFFLINE_FILES = ("eval_hf.json", "eval_ollama_subset50.json")
SOURCE = "offline_import"


def golden_set_name(data: dict[str, Any]) -> str:
    subset = data.get("subset") or {}
    if subset.get("n"):
        return f"sciq_test_subset{subset['n']}"
    return f"sciq_test_{data.get('n_items')}"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def import_file(db: Session, path: Path) -> list[EvalRun]:
    """Returns the runs created (empty if this file was already imported)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    key = {"file": path.name, "created_at": data.get("created_at"), "items_fingerprint": data.get("items_fingerprint")}
    for cfg in db.scalars(select(EvalRun.config_json).where(EvalRun.source == SOURCE)):
        if cfg and all(cfg.get(k) == v for k, v in key.items()):
            return []
    created = _parse_ts(data.get("created_at"))
    config = key | {
        "backend": data.get("backend"),
        "n_items": data.get("n_items"),
        "by_task": data.get("by_task"),
        "decoding": data.get("decoding"),
        "json_mode": data.get("json_mode"),
        "base_model": data.get("base_model"),
        "base_model_revision": data.get("base_model_revision"),
        "gpu": data.get("gpu"),
        "machine": data.get("machine"),
        "processor": data.get("processor"),
        "subset": {k: v for k, v in (data.get("subset") or {}).items() if k != "ids"} or None,
        "latency_note": data.get("latency_note"),
    }
    runs = []
    for label, metrics in (data.get("models") or {}).items():
        run = EvalRun(golden_set=golden_set_name(data), generator=label, model=metrics.get("model"), source=SOURCE,
                      n_items=metrics.get("n_items"), prompt_versions=data.get("prompt_versions"),
                      config_json=config, metrics_json=metrics, status="ok", finished_at=created)
        if created is not None:
            run.started_at = created
        db.add(run)
        runs.append(run)
    db.commit()
    return runs


def import_all(db: Session, results_dir: Path) -> dict[str, int | str]:
    """{file name: runs created, or "missing"}."""
    out: dict[str, int | str] = {}
    for name in OFFLINE_FILES:
        p = results_dir / name
        out[name] = len(import_file(db, p)) if p.is_file() else "missing"
    return out
