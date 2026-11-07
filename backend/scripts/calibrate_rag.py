"""Calibrate RAG_MIN_SCORE from REAL retrieval scores on one of your lectures.

    cd backend
    python -m scripts.calibrate_rag --lecture-id <id>
    python -m scripts.calibrate_rag --lecture-id <id> --questions eval/calibration/my_questions.json

It indexes the lecture if needed, embeds every on-topic and off-topic question exactly as /ask
does (bge query prefix, top RAG_TOP_K from Chroma, score = 1 - cosine distance), prints the best
score per question and the distribution per group, and PROPOSES a threshold computed from those
scores. Nothing is guessed. If the two groups don't overlap, the proposal is the midpoint of the
gap; if they do, it is the threshold with the best balanced accuracy (ties go to the lower value,
because the answer prompt is a second filter that can still refuse).

It does not call any LLM (free; only the local embedding model runs). Embedding calls are logged
in llm_calls with task=rag_calibration. The results are saved as JSON in ../storage/manual-test/.
The database must be running and migrated; the lecture must have a transcript.
"""

import argparse
import json
import statistics
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import BACKEND_DIR, REPO_ROOT, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.models.lecture import Lecture
from app.services.embeddings import get_embedding_client
from app.services.indexing import get_indexer
from app.services.rag import mmss
from app.services.vectorstore import get_vector_store

DEFAULT_QUESTIONS = BACKEND_DIR / "eval" / "calibration" / "demo_lecture_questions.json"


def propose(on: list[float], off: list[float]) -> dict:
    """Threshold proposal from the observed top scores (no prior assumptions)."""
    lo_on, hi_off = min(on), max(off)
    if lo_on > hi_off:
        return {"threshold": round((lo_on + hi_off) / 2, 3), "method": "midpoint_of_gap",
                "gap": round(lo_on - hi_off, 4), "on_refused": 0, "off_answered": 0}
    candidates = sorted(set(on + off + [(a + b) / 2 for a, b in zip(sorted(on + off), sorted(on + off)[1:])]))
    best = None
    for t in candidates:
        on_ok = sum(s >= t for s in on) / len(on)
        off_ok = sum(s < t for s in off) / len(off)
        key = ((on_ok + off_ok) / 2, -t)  # best balanced accuracy, then the lower threshold
        if best is None or key > best[0]:
            best = (key, t, on_ok, off_ok)
    _, t, on_ok, off_ok = best
    return {"threshold": round(t, 3), "method": "best_balanced_accuracy (groups overlap)",
            "balanced_accuracy": round((on_ok + off_ok) / 2, 3),
            "on_refused": round((1 - on_ok) * len(on)), "off_answered": round((1 - off_ok) * len(off))}


def describe(scores: list[float]) -> str:
    q = statistics.quantiles(scores, n=4) if len(scores) >= 2 else [scores[0]] * 3
    return (f"min {min(scores):.3f}  q1 {q[0]:.3f}  median {statistics.median(scores):.3f}  "
            f"q3 {q[2]:.3f}  max {max(scores):.3f}  mean {statistics.fmean(scores):.3f}")


def bar_chart(on: list[float], off: list[float], width: int = 40) -> list[str]:
    lo = min(on + off)
    hi = max(on + off)
    span = (hi - lo) or 1.0
    lines = []
    for label, mark, group in (("on ", "o", on), ("off", "x", off)):
        counts = [0] * (width + 1)
        for s in group:
            counts[round((s - lo) / span * width)] += 1
        cells = "".join(" " if c == 0 else mark if c == 1 else str(min(c, 9)) for c in counts)
        lines.append(f"  {label} |{cells}|")
    lines.append(f"       {lo:<.3f}{' ' * (width - 9)}{hi:>.3f}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lecture-id", required=True, type=uuid.UUID)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    args = parser.parse_args()

    configure_logging("WARNING", json_logs=False)
    settings = get_settings()
    qs = json.loads(args.questions.read_text(encoding="utf-8"))
    on_q, off_q = qs["on_topic"], qs["off_topic"]

    with get_session_factory()() as db:
        lecture = db.get(Lecture, args.lecture_id)
        if lecture is None:
            print(f"Lecture {args.lecture_id} not found")
            return 1
        print(f"Lecture   : {lecture.title} ({mmss(lecture.duration_sec or 0)}), status {lecture.status}")
        print(f"Model     : {settings.embedding_model}   top_k {settings.rag_top_k}   "
              f"current RAG_MIN_SCORE {settings.rag_min_score}")
        try:
            idx = get_indexer().ensure_indexed(db, lecture.id, lecture.user_id)
        except AppError as exc:
            print(f"FAILED to index [{exc.code}] {exc.message}")
            return 1
        print(f"Index     : {idx.chunks} chunks ({'indexed now' if idx.indexed_now else 'already indexed'})")

        vectors = get_embedding_client().embed_queries(on_q + off_q, task="rag_calibration",
                                                       lecture_id=lecture.id, user_id=lecture.user_id)
        store = get_vector_store()
        rows = []
        for i, (q, v) in enumerate(zip(on_q + off_q, vectors)):
            hits = store.query(lecture.id, v, settings.rag_top_k)
            top = max((h.score for h in hits), default=0.0)
            best = max(hits, key=lambda h: h.score) if hits else None
            rows.append({"group": "on" if i < len(on_q) else "off", "question": q, "top_score": round(top, 4),
                         "scores": [round(h.score, 4) for h in sorted(hits, key=lambda h: -h.score)],
                         "best_chunk": None if best is None else
                         f"{mmss(best.metadata['start'])}-{mmss(best.metadata['end'])}"})

    on = [r["top_score"] for r in rows if r["group"] == "on"]
    off = [r["top_score"] for r in rows if r["group"] == "off"]
    prop = propose(on, off)

    for group, title in (("on", "ON-TOPIC"), ("off", "OFF-TOPIC")):
        print(f"\n{title} (best score, best chunk, question)")
        for r in sorted((r for r in rows if r["group"] == group), key=lambda r: -r["top_score"]):
            print(f"  {r['top_score']:.3f}  [{r['best_chunk']}]  {r['question']}")
    print("\nDistribution of the best score per question")
    print(f"  on-topic  : {describe(on)}")
    print(f"  off-topic : {describe(off)}")
    print("\n".join(bar_chart(on, off)))
    print("  (o = one on-topic question, x = one off-topic question, a digit = that many in the same cell)")

    print(f"\nProposed RAG_MIN_SCORE = {prop['threshold']}   ({prop['method']})")
    if prop["method"] == "midpoint_of_gap":
        print(f"  The groups are separated by a gap of {prop['gap']:.3f}: lowest on-topic {min(on):.3f}, "
              f"highest off-topic {max(off):.3f}.")
    else:
        print(f"  The groups overlap. At this value {prop['on_refused']} on-topic question(s) would be refused "
              f"and {prop['off_answered']} off-topic question(s) would reach the answer prompt "
              "(which can still refuse them).")
    print(f"  At the current value {settings.rag_min_score}: "
          f"{sum(s < settings.rag_min_score for s in on)} on-topic refused, "
          f"{sum(s >= settings.rag_min_score for s in off)} off-topic passed the threshold.")
    print(f"  Based on {len(on)} + {len(off)} questions on one lecture: a starting value, to be re-checked "
          "with the golden set in Phase 11.")

    out_dir = REPO_ROOT / "storage" / "manual-test"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"rag_calibration_{args.lecture_id}.json"
    dest.write_text(json.dumps({
        "lecture_id": str(args.lecture_id), "run_at": datetime.now(UTC).isoformat(),
        "embedding_model": settings.embedding_model, "top_k": settings.rag_top_k,
        "questions_file": str(args.questions), "current_min_score": settings.rag_min_score,
        "proposal": prop, "rows": rows,
    }, indent=2), encoding="utf-8")
    print(f"\nSaved {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
