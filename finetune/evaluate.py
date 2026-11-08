"""Base vs fine-tuned evaluation on the same 500 SciQ test items (IMPLEMENTATION_PLAN §8.4).

Two ways to run it:

1. In the Colab notebook (GPU, recommended for the comparison): the notebook calls
   `run_comparison(HFBackend(model, tokenizer), ...)` directly (same 4-bit weights, adapter off/on).

2. Locally against Ollama (CPU latency, the exact serving path of the app):
       python evaluate.py --backend ollama --items data/test_eval.jsonl \
           --base-model study-buddy-qwen-base --finetuned-model study-buddy-qwen
   Add `--subset 50` for a seeded 50-item sample with the same task mix (CPU is slow):
   it writes results/eval_ollama_subset50.json and records the sampled ids.

Writes (nothing else, and no numbers anywhere else):
    results/eval_<backend>.json                     summary per model + config + versions
    results/predictions_<backend>_<label>.jsonl     raw output and per-item scores
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import random
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_runner import MAX_NEW_TOKENS, HFBackend, OllamaBackend, load_items  # noqa: E402
from metrics import score_items  # noqa: E402
from prompts import PROMPT_VERSIONS  # noqa: E402

N_EVAL_ITEMS = 500
SUBSET_SEED = 3407  # same seed as prepare_data.py


def items_fingerprint(items: list[dict[str, Any]]) -> str:
    """Hash of the item ids + prompts, so two result files can be checked to use the same test set."""
    h = hashlib.sha256()
    for it in items:
        h.update(it["id"].encode())
        for m in it["messages"]:
            if m["role"] != "assistant":
                h.update(m["content"].encode())
    return h.hexdigest()[:16]


def run_comparison(
    backend: HFBackend | OllamaBackend,
    items: list[dict[str, Any]],
    models: dict[str, str],
    out_dir: str | Path,
    backend_name: str,
    extra: dict[str, Any] | None = None,
    max_new_tokens: int = MAX_NEW_TOKENS,
    warmup: bool = False,
) -> dict[str, Any]:
    """`models` maps label ("base"/"finetuned") → model id for the backend (HF: the label itself).

    warmup=True sends one untimed request per model first, so loading the model isn't counted as latency.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "backend": backend_name,
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "n_items": len(items),
        "items_fingerprint": items_fingerprint(items),
        "by_task": {t: sum(1 for i in items if i["task"] == t) for t in ("gqa", "refusal", "mcq")},
        "decoding": {"greedy": True, "max_new_tokens": max_new_tokens, "enable_thinking": False},
        "prompt_versions": PROMPT_VERSIONS,
        "python": platform.python_version(),
        "warmup_request_per_model": warmup,
        **(extra or {}),
        "models": {},
    }
    for label, model_id in models.items():
        print(f"[{backend_name}] {label} ({model_id}): {len(items)} items")
        if warmup and items:
            backend.generate(model_id, items[:1], max_new_tokens=max_new_tokens)  # untimed, not scored
        t0 = time.perf_counter()

        def progress(n: int, _label: str = label) -> None:
            if n % 50 == 0 or n == len(items):
                print(f"  {_label}: {n}/{len(items)}")

        outputs = backend.generate(model_id, items, max_new_tokens=max_new_tokens, progress=progress)
        wall_s = time.perf_counter() - t0
        scored = score_items(items, outputs)
        errors = sum(1 for o in outputs if o.get("error"))
        with (out / f"predictions_{backend_name}_{label}.jsonl").open("w", encoding="utf-8") as f:
            for item, o, row in zip(items, outputs, scored["per_item"]):
                f.write(json.dumps({**row, "output": o["text"], "latency_ms": o.get("latency_ms"),
                                    "error": o.get("error"), "gold": item["messages"][-1]["content"]},
                                   ensure_ascii=False) + "\n")
        report["models"][label] = {"model": model_id, "wall_time_s": round(wall_s, 1),
                                   "request_errors": errors, **scored["summary"]}
    path = out / f"eval_{backend_name}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"-> {path}")
    return report


def stratified_subset(items: list[dict[str, Any]], n: int, seed: int = SUBSET_SEED) -> list[dict[str, Any]]:
    """n items with the same task mix as `items` (largest-remainder rounding), seeded, in file order."""
    if n >= len(items):
        return list(items)
    tasks: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        tasks.setdefault(it["task"], []).append(i)
    exact = {t: n * len(ix) / len(items) for t, ix in tasks.items()}
    counts = {t: int(v) for t, v in exact.items()}
    for t in sorted(exact, key=lambda t: exact[t] - counts[t], reverse=True)[: n - sum(counts.values())]:
        counts[t] += 1
    rng = random.Random(seed)
    chosen = sorted(i for t in sorted(tasks) for i in rng.sample(tasks[t], counts[t]))
    return [items[i] for i in chosen]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["ollama"], default="ollama",
                    help="the HF/GPU backend runs inside the notebook (it needs the loaded model)")
    ap.add_argument("--items", default="data/test_eval.jsonl")
    ap.add_argument("--out", default="results")
    ap.add_argument("--base-url", default="http://localhost:11434/v1")
    ap.add_argument("--base-model", default="study-buddy-qwen-base")
    ap.add_argument("--finetuned-model", default="study-buddy-qwen")
    ap.add_argument("--limit", type=int, default=None, help="only the first N items (a quick smoke test)")
    ap.add_argument("--subset", type=int, default=None,
                    help=f"N items sampled with the full set's task mix (seed {SUBSET_SEED}) -> eval_ollama_subsetN.json")
    ap.add_argument("--max-new-tokens", type=int, default=MAX_NEW_TOKENS)
    args = ap.parse_args(argv)
    if args.limit and args.subset:
        ap.error("use --limit or --subset, not both")

    all_items = load_items(args.items)
    if len(all_items) != N_EVAL_ITEMS:
        print(f"warning: expected {N_EVAL_ITEMS} items, found {len(all_items)}")
    extra: dict[str, Any] = {"ollama_base_url": args.base_url, "machine": platform.platform(),
                             "processor": platform.processor(), "json_mode": True}
    if args.subset:
        items = stratified_subset(all_items, args.subset)
        name = f"ollama_subset{len(items)}"
        extra["subset"] = {"n": len(items), "of_items": len(all_items), "seed": SUBSET_SEED,
                           "full_items_fingerprint": items_fingerprint(all_items), "ids": [it["id"] for it in items]}
    elif args.limit:
        items, name = all_items[: args.limit], f"ollama_smoke{args.limit}"
    else:
        items, name = all_items, "ollama"
    backend = OllamaBackend(args.base_url)
    run_comparison(backend, items, {"base": args.base_model, "finetuned": args.finetuned_model}, args.out, name,
                   extra=extra, max_new_tokens=args.max_new_tokens, warmup=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
