"""Length of the generated outputs per model and task, from the saved predictions (no new generations).

Used to explain latency: in the batched GPU evaluation every item's latency is (batch time / batch size),
and a batch takes as long as its longest generation, so longer answers mean higher latency.
Tokens are counted with the base model's tokenizer when `transformers` is installed (--tokenizer),
otherwise only characters are reported.

Usage (repo root):
  Windows:      backend\\.venv\\Scripts\\python finetune\\output_stats.py --backend hf
  macOS/Linux:  backend/.venv/bin/python finetune/output_stats.py --backend hf
Writes results/output_stats_<backend>.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eval_runner import load_items

HERE = Path(__file__).resolve().parent


def length_stats(predictions: list[dict[str, Any]], count_tokens: Callable[[str], int] | None = None,
                 batch_size: int = 0) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {"all": list(predictions)}
    for p in predictions:
        groups.setdefault(p["task"], []).append(p)
    out = {}
    for task, rows in groups.items():
        chars = [len(r["output"]) for r in rows]
        entry: dict[str, Any] = {"n": len(rows), "mean_chars": round(statistics.fmean(chars), 1) if chars else None}
        if count_tokens and rows:
            entry["mean_tokens"] = round(statistics.fmean(count_tokens(r["output"]) for r in rows), 1)
        out[task] = entry
    if count_tokens and batch_size:
        # Batches in file order, as HFBackend ran them: each batch lasts as long as its longest generation.
        toks = [count_tokens(p["output"]) for p in predictions]
        maxes = [max(toks[i : i + batch_size]) for i in range(0, len(toks), batch_size)]
        out["all"]["batch_size"] = batch_size
        out["all"]["mean_batch_max_tokens"] = round(statistics.fmean(maxes), 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backend", default="hf")
    ap.add_argument("--results", default=str(HERE / "results"))
    ap.add_argument("--tokenizer", default="", help="e.g. unsloth/Qwen3-1.7B (needs transformers; optional)")
    ap.add_argument("--batch-size", type=int, default=8, help="batch size of the run (the notebook's step 8 uses 8)")
    args = ap.parse_args()

    count = None
    if args.tokenizer:
        from prepare_data import BASE_MODEL_REVISION  # noqa: PLC0415
        from transformers import AutoTokenizer  # noqa: PLC0415

        tok = AutoTokenizer.from_pretrained(args.tokenizer, revision=BASE_MODEL_REVISION)
        count = lambda s: len(tok(s, add_special_tokens=False)["input_ids"])  # noqa: E731

    res = Path(args.results)
    eval_file = json.loads((res / f"eval_{args.backend}.json").read_text(encoding="utf-8"))
    out: dict[str, Any] = {
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "source_eval": f"eval_{args.backend}.json",
        "items_fingerprint": eval_file.get("items_fingerprint"),
        "tokenizer": args.tokenizer or None,
        "models": {},
    }
    for label in eval_file["models"]:
        preds = load_items(str(res / f"predictions_{args.backend}_{label}.jsonl"))
        out["models"][label] = length_stats(preds, count, args.batch_size if args.backend == "hf" else 0)
    path = res / f"output_stats_{args.backend}.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for label, m in out["models"].items():
        print(label, {t: (v.get("mean_tokens"), v["mean_chars"]) for t, v in m.items()})
    print("->", path)


if __name__ == "__main__":
    main()
