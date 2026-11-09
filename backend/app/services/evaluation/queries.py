"""Read-only queries over eval_runs / eval_items for the LLMOps API and the export script."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.lecture import Lecture
from app.models.llmops import EvalItem, EvalRun

GENERATOR_ORDER = {"cloud": 0, "finetuned": 1, "base": 2}


def _run_dict(run: EvalRun, title: str | None) -> dict[str, Any]:
    return {"id": run.id, "golden_set": run.golden_set, "generator": run.generator, "model": run.model,
            "source": run.source, "lecture_id": run.lecture_id, "lecture_title": title, "n_items": run.n_items,
            "status": run.status, "error": run.error, "started_at": run.started_at, "finished_at": run.finished_at,
            "prompt_versions": run.prompt_versions, "config": run.config_json, "metrics": run.metrics_json}


def list_runs(db: Session, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.execute(select(EvalRun, Lecture.title).join(Lecture, Lecture.id == EvalRun.lecture_id, isouter=True)
                      .order_by(EvalRun.started_at.desc()).limit(limit)).all()
    return [_run_dict(r, t) for r, t in rows]


def get_run(db: Session, run_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(select(EvalRun, Lecture.title).join(Lecture, Lecture.id == EvalRun.lecture_id, isouter=True)
                     .where(EvalRun.id == run_id)).first()
    if row is None:
        raise NotFoundError("Evaluation run not found", code="EVAL_RUN_NOT_FOUND")
    items = db.scalars(select(EvalItem).where(EvalItem.run_id == run_id).order_by(EvalItem.item_key)).all()
    return _run_dict(row[0], row[1]) | {"items": [
        {"id": i.id, "item_key": i.item_key, "kind": i.kind, "question": i.question, "answerable": i.answerable,
         "gold_start": i.gold_start, "gold_end": i.gold_end, "reference_answer": i.reference_answer,
         "predicted_answer": i.predicted_answer, "predicted_answerable": i.predicted_answerable,
         "refusal_reason": i.refusal_reason, "top_score": i.top_score, "latency_ms": i.latency_ms,
         "status": i.status, "retrieved": i.retrieved_json, "metrics": i.metrics_json} for i in items]}


def compare(db: Session, golden_set: str | None = None) -> dict[str, Any]:
    """Latest finished harness run per generator for one golden set (default: the set of the most
    recent harness run), its retrieval run, and the latest offline (SciQ) runs."""
    harness = list(db.scalars(select(EvalRun).where(EvalRun.source == "harness", EvalRun.status != "running")
                              .order_by(EvalRun.started_at.desc())))
    sets = list(dict.fromkeys(r.golden_set for r in harness))
    chosen = golden_set or (sets[0] if sets else None)
    latest: dict[str, EvalRun] = {}
    for r in harness:
        if r.golden_set == chosen and r.generator not in latest:
            latest[r.generator] = r
    titles = dict(db.execute(select(Lecture.id, Lecture.title)).all())
    retrieval = latest.pop("retrieval", None)
    gens = sorted(latest.values(), key=lambda r: (GENERATOR_ORDER.get(r.generator, 9), r.generator))

    offline = list(db.scalars(select(EvalRun).where(EvalRun.source == "offline_import")
                              .order_by(EvalRun.started_at.desc())))
    off_latest: dict[tuple[str, str], EvalRun] = {}
    for r in offline:
        off_latest.setdefault((r.golden_set, r.generator), r)
    return {
        "golden_set": chosen,
        "golden_sets": sets,
        "retrieval": _run_dict(retrieval, titles.get(retrieval.lecture_id)) if retrieval else None,
        "generators": [_run_dict(r, titles.get(r.lecture_id)) for r in gens],
        "offline": [_run_dict(r, None) for r in sorted(off_latest.values(),
                                                      key=lambda r: (r.golden_set,
                                                                     GENERATOR_ORDER.get(r.generator, 9)))],
    }
