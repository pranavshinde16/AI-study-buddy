"""Secondary MCQ checks, computed again from the saved predictions (no new generations).

Added AFTER the first results (2026-11-08). The primary metric stays `mcq.answer_matches_source_rate` in
eval_<backend>.json: the option the model marks correct must equal SciQ's correct answer exactly (after
normalisation). That is strict, because a passage supports several questions and the model may ask about
a different fact, or word the same answer differently ("exothermic" vs "exothermic reactions").

The two checks here are looser and are reported as secondary only:
- loose_match_rate      the marked option, with a leading "A." label removed, contains SciQ's correct
                        answer or is contained in it (whole words).
- answer_in_passage_rate the marked option appears word for word in the passage: the "correct" answer is
                        at least taken from the text (it says nothing about whether the question fits it).
Both are computed over all MCQ items (an invalid JSON counts as a miss) and over the valid ones only.

Usage (repo root):
  Windows:      backend\\.venv\\Scripts\\python finetune\\rescore_mcq.py --backend hf
  macOS/Linux:  backend/.venv/bin/python finetune/rescore_mcq.py --backend hf
Writes results/mcq_secondary_<backend>.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

from eval_runner import load_items
from metrics import contains_answer, mcq_loose_match, normalize, parse_json, parse_mcq, strip_option_label

HERE = Path(__file__).resolve().parent
LETTERS = ("A", "B", "C", "D")


def passage_of(item: dict[str, Any]) -> str:
    user = next(m["content"] for m in item["messages"] if m["role"] == "user")
    return user.split("Passage:", 1)[1].strip() if "Passage:" in user else user


def invalid_reason(text: str) -> str:
    """Why parse_mcq rejected an output (for the failure analysis)."""
    d = parse_json(text)
    if not isinstance(d, dict):
        return "not_parseable_json"
    opts = d.get("options")
    if not isinstance(opts, list) or len(opts) != 4 or not all(isinstance(o, str) and o.strip() for o in opts):
        return "options_not_4_strings"
    if len({normalize(o) for o in opts}) != 4:
        return "duplicate_options"
    return "bad_question_or_answer_field"


def rescore(items: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {it["id"]: it for it in items}
    rows = []
    for pred in predictions:
        if pred["task"] != "mcq":
            continue
        item = by_id[pred["id"]]
        parsed = parse_mcq(pred["output"])
        row = {"id": pred["id"], "json_valid": parsed is not None, "invalid_reason": None if parsed else invalid_reason(pred["output"]),
               "strict_match": False, "loose_match": False, "answer_in_passage": False}
        if parsed:
            chosen = parsed["options"][LETTERS.index(parsed["answer"])]
            row["strict_match"] = bool(pred.get("answer_matches_source"))
            row["loose_match"] = mcq_loose_match(chosen, item["meta"]["correct_answer"])
            row["answer_in_passage"] = contains_answer(passage_of(item), strip_option_label(chosen))
        rows.append(row)

    def rate(key: str, only_valid: bool) -> float | None:
        xs = [r[key] for r in rows if r["json_valid"] or not only_valid]
        return round(sum(xs) / len(xs), 4) if xs else None

    return {
        "n_mcq": len(rows),
        "n_json_valid": sum(r["json_valid"] for r in rows),
        "strict_answer_matches_source_rate": rate("strict_match", False),  # = eval file's primary metric
        "loose_match_rate": rate("loose_match", False),
        "answer_in_passage_rate": rate("answer_in_passage", False),
        "valid_only": {k: rate(k, True) for k in ("strict_match", "loose_match", "answer_in_passage")},
        "invalid_reasons": dict(Counter(r["invalid_reason"] for r in rows if r["invalid_reason"])),
        "per_item": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backend", default="hf", help="hf or ollama (which predictions_<backend>_*.jsonl to read)")
    ap.add_argument("--items", default=str(HERE / "data" / "test_eval.jsonl"))
    ap.add_argument("--results", default=str(HERE / "results"))
    args = ap.parse_args()

    res = Path(args.results)
    eval_file = json.loads((res / f"eval_{args.backend}.json").read_text(encoding="utf-8"))
    items = load_items(args.items)
    out: dict[str, Any] = {
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "note": "Secondary MCQ checks added after the first results; the primary metric is "
                "mcq.answer_matches_source_rate in the eval file. Re-scored from the saved predictions.",
        "source_eval": f"eval_{args.backend}.json",
        "items_fingerprint": eval_file.get("items_fingerprint"),
        "models": {},
    }
    for label in eval_file["models"]:
        preds = load_items(str(res / f"predictions_{args.backend}_{label}.jsonl"))
        out["models"][label] = rescore(items, preds)
        primary = eval_file["models"][label]["mcq"]["answer_matches_source_rate"]
        got = out["models"][label]["strict_answer_matches_source_rate"]
        assert primary == got, f"{label}: strict rate {got} differs from the eval file's {primary}"
    path = res / f"mcq_secondary_{args.backend}.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for label, m in out["models"].items():
        print(f"{label}: strict {m['strict_answer_matches_source_rate']} | loose {m['loose_match_rate']} | "
              f"in passage {m['answer_in_passage_rate']} (n={m['n_mcq']}, valid={m['n_json_valid']}) | invalid: {m['invalid_reasons']}")
    print("->", path)


if __name__ == "__main__":
    main()
