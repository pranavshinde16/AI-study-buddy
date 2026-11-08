"""Build the SciQ fine-tuning and evaluation sets (IMPLEMENTATION_PLAN §8.1–8.2).

Run (Colab, or any machine with `pip install -r requirements-colab.txt`):
    python prepare_data.py --out data --stats results/data_stats.json

Outputs (JSONL, one example per line: {"id", "task", "messages", "meta"}):
    data/train.jsonl     3,000 from the official train split      (2,250 gqa / 450 refusal / 300 mcq)
    data/val.jsonl         300 from the official validation split (225 / 45 / 30)
    data/test_eval.jsonl   500 from the official test split       (375 / 75 / 50), never trained on
    results/data_stats.json  real counts from this run (rows, empty supports dropped, token lengths, …)

Tasks (all in the app's format; see prompts.py):
    gqa      question + excerpts [C1..Ck]: the item's own support + 1-2 supports of other items that
             don't contain the answer, shuffled → {"answerable": true, "answer": "<answer>. <support
             sentence containing it> [Cn]", "citations": ["Cn"]}. The sentence comes from SciQ.
    refusal  question + 2-3 supports of OTHER items that don't contain its answer
             → {"answerable": false, "answer": REFUSAL_ANSWER, "citations": []}
    mcq      passage (support) → {"question", "options" (correct + SciQ's 3 distractors, shuffled), "answer"}

Each split uses only its own items as distractor excerpts, so test text never appears in training.
Examples longer than --max-seq-len tokens (chat template, thinking off) first lose distractor
excerpts; if still too long they are replaced by the next unused item. Seeded, so reruns are identical.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import contains_answer, normalize  # noqa: E402
from prompts import (  # noqa: E402
    LETTERS,
    PROMPT_VERSIONS,
    REFUSAL_ANSWER,
    mcq_messages,
    mcq_target,
    rag_messages,
    rag_target,
)

# ---- pinned sources (also written to data_stats.json and training.json) ----
SCIQ_DATASET = "allenai/sciq"
SCIQ_REVISION = "2c94ad3e1aafab77146f384e23536f97a4849815"
BASE_MODEL = "unsloth/Qwen3-1.7B"
BASE_MODEL_REVISION = "6262b50d6c1f8ee5e4ac750d710c33603bfc2a0c"

SEED = 3407
MAX_SEQ_LEN = 1024
# (split, total, gqa share, refusal share, mcq share): ≈75 / 15 / 10 %.
PLAN = {
    "train": (3000, 2250, 450, 300),
    "validation": (300, 225, 45, 30),
    "test": (500, 375, 75, 50),
}
OUT_NAMES = {"train": "train.jsonl", "validation": "val.jsonl", "test": "test_eval.jsonl"}

_SENT = re.compile(r"(?<=[.!?])\s+")
MAX_JUSTIFICATION_CHARS = 400


@dataclass(frozen=True)
class SciqItem:
    index: int
    question: str
    correct_answer: str
    distractors: tuple[str, str, str]
    support: str


def clean_rows(rows: Sequence[dict[str, Any]]) -> tuple[list[SciqItem], int]:
    """Keep rows with a non-empty support; returns (items, number dropped)."""
    items, dropped = [], 0
    for i, r in enumerate(rows):
        support = (r.get("support") or "").strip()
        if not support or not (r.get("question") or "").strip() or not (r.get("correct_answer") or "").strip():
            dropped += 1
            continue
        items.append(
            SciqItem(
                index=i,
                question=r["question"].strip(),
                correct_answer=r["correct_answer"].strip(),
                distractors=(r["distractor1"].strip(), r["distractor2"].strip(), r["distractor3"].strip()),
                support=support,
            )
        )
    return items, dropped


def supporting_sentence(support: str, answer: str) -> str | None:
    """First sentence of the support that contains the answer (whole words), if short enough."""
    for sent in _SENT.split(support):
        s = sent.strip()
        if s and contains_answer(s, answer) and len(s) <= MAX_JUSTIFICATION_CHARS:
            return s
    return None


def reference_answer(item: SciqItem) -> tuple[str, bool]:
    """The answer text the model learns (citation added separately). Returns (text, has_sentence)."""
    ans = item.correct_answer[0].upper() + item.correct_answer[1:]
    sent = supporting_sentence(item.support, item.correct_answer)
    if sent:
        return f"{ans}. {sent}", True
    return f"{ans}.", False


def pick_unrelated(pool: Sequence[SciqItem], item: SciqItem, k: int, rng: random.Random) -> list[SciqItem]:
    """k other items whose support does not contain `item`'s answer (so the excerpts can't answer it)."""
    out: list[SciqItem] = []
    seen = {item.index}
    norm_support = normalize(item.support)
    for _ in range(50 * k):
        if len(out) == k:
            break
        cand = pool[rng.randrange(len(pool))]
        if cand.index in seen or normalize(cand.support) == norm_support:
            continue
        seen.add(cand.index)
        if contains_answer(cand.support, item.correct_answer):
            continue
        out.append(cand)
    return out


def build_gqa(item: SciqItem, pool: Sequence[SciqItem], rng: random.Random) -> dict[str, Any]:
    others = pick_unrelated(pool, item, rng.choice((1, 2)), rng)
    texts = [item.support] + [o.support for o in others]
    order = list(range(len(texts)))
    rng.shuffle(order)
    excerpts = [texts[i] for i in order]
    gold = f"C{order.index(0) + 1}"
    ref, has_sentence = reference_answer(item)
    answer = f"{ref} [{gold}]" if not ref.endswith(".") else f"{ref[:-1]} [{gold}]."
    return {
        "task": "gqa",
        "messages": rag_messages(item.question, excerpts)
        + [{"role": "assistant", "content": rag_target(True, answer, [gold])}],
        "meta": {
            "sciq_index": item.index,
            "correct_answer": item.correct_answer,
            "reference_answer": ref,
            "gold_citation": gold,
            "n_excerpts": len(excerpts),
            "has_support_sentence": has_sentence,
            "excerpt_sources": [item.index] + [o.index for o in others],
            "excerpt_order": order,
        },
        "_src": {"question": item.question, "excerpts": excerpts},
    }


def build_refusal(item: SciqItem, pool: Sequence[SciqItem], rng: random.Random) -> dict[str, Any]:
    others = pick_unrelated(pool, item, rng.choice((2, 3)), rng)
    excerpts = [o.support for o in others]
    return {
        "task": "refusal",
        "messages": rag_messages(item.question, excerpts)
        + [{"role": "assistant", "content": rag_target(False, REFUSAL_ANSWER, [])}],
        "meta": {
            "sciq_index": item.index,
            "correct_answer": item.correct_answer,
            "n_excerpts": len(excerpts),
            "excerpt_sources": [o.index for o in others],
        },
        "_src": {"question": item.question, "excerpts": excerpts},
    }


def build_mcq(item: SciqItem, rng: random.Random) -> dict[str, Any]:
    options = [item.correct_answer, *item.distractors]
    rng.shuffle(options)
    letter = LETTERS[options.index(item.correct_answer)]
    return {
        "task": "mcq",
        "messages": mcq_messages(item.support)
        + [{"role": "assistant", "content": mcq_target(item.question, options, letter)}],
        "meta": {"sciq_index": item.index, "correct_answer": item.correct_answer, "answer_letter": letter},
    }


def _drop_last_distractor(ex: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild a gqa/refusal example with one fewer unrelated excerpt (never the gold one)."""
    src = ex.get("_src")
    if ex["task"] == "mcq" or not src:
        return None
    texts: list[str] = list(src["excerpts"])
    meta = ex["meta"]
    if ex["task"] == "gqa":
        if len(texts) <= 1:
            return None
        gold_pos = int(meta["gold_citation"][1:]) - 1
        drop = max(i for i in range(len(texts)) if i != gold_pos)
        texts.pop(drop)
        new_gold = f"C{(gold_pos if drop > gold_pos else gold_pos - 1) + 1}"
        target = json.loads(ex["messages"][2]["content"])
        answer = target["answer"].replace(f"[{meta['gold_citation']}]", f"[{new_gold}]")
        msgs = rag_messages(src["question"], texts) + [{"role": "assistant", "content": rag_target(True, answer, [new_gold])}]
        new_meta = {**meta, "gold_citation": new_gold, "n_excerpts": len(texts)}
    else:
        if len(texts) <= 1:
            return None
        texts.pop()
        msgs = rag_messages(src["question"], texts) + [ex["messages"][2]]
        new_meta = {**meta, "n_excerpts": len(texts)}
    new_meta["reduced"] = meta.get("reduced", 0) + 1
    return {**ex, "messages": msgs, "meta": new_meta, "_src": {**src, "excerpts": texts}}


def fit_length(ex: dict[str, Any], count_tokens: Callable[[list[dict[str, str]]], int], max_len: int) -> tuple[dict[str, Any] | None, int]:
    """Drop unrelated excerpts until the example fits; (example or None, final length)."""
    n = count_tokens(ex["messages"])
    while n > max_len:
        smaller = _drop_last_distractor(ex)
        if smaller is None:
            return None, n
        ex, n = smaller, count_tokens(smaller["messages"])
    return ex, n


def build_split(
    items: Sequence[SciqItem],
    plan: tuple[int, int, int, int],
    split: str,
    count_tokens: Callable[[list[dict[str, str]]], int],
    max_len: int = MAX_SEQ_LEN,
    seed: int = SEED,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deterministically build one split's examples and its stats."""
    total, n_gqa, n_ref, n_mcq = plan
    if n_gqa + n_ref + n_mcq != total:
        raise ValueError("task counts must add up to the total")
    rng = random.Random(f"{seed}-{split}")
    order = list(range(len(items)))
    rng.shuffle(order)
    queue = iter(order)
    examples: list[dict[str, Any]] = []
    lengths: list[int] = []
    stats: Counter[str] = Counter()

    for task, want in (("gqa", n_gqa), ("refusal", n_ref), ("mcq", n_mcq)):
        made = 0
        while made < want:
            try:
                item = items[next(queue)]
            except StopIteration:
                raise ValueError(f"{split}: not enough items for {task} ({made}/{want})") from None
            if task == "gqa":
                ex = build_gqa(item, items, rng)
            elif task == "refusal":
                ex = build_refusal(item, items, rng)
                if ex["meta"]["n_excerpts"] == 0:
                    stats["skipped_no_unrelated_excerpt"] += 1
                    continue
            else:
                ex = build_mcq(item, rng)
            fitted, n = fit_length(ex, count_tokens, max_len)
            if fitted is None:
                stats[f"dropped_too_long_{task}"] += 1
                continue
            if fitted["meta"].get("reduced"):
                stats[f"reduced_excerpts_{task}"] += 1
            if task == "gqa" and not fitted["meta"]["has_support_sentence"]:
                stats["gqa_without_support_sentence"] += 1
            fitted.pop("_src", None)
            fitted["id"] = f"{split}-{task}-{item.index}"
            examples.append(fitted)
            lengths.append(n)
            made += 1

    rng.shuffle(examples)
    summary = {
        "examples": len(examples),
        "by_task": dict(Counter(e["task"] for e in examples)),
        "events": dict(sorted(stats.items())),
        "tokens": {
            "max": max(lengths),
            "mean": round(statistics.fmean(lengths), 1),
            "p50": sorted(lengths)[len(lengths) // 2],
            "p95": sorted(lengths)[int(0.95 * (len(lengths) - 1))],
        },
    }
    return examples, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data", help="folder for the JSONL files")
    ap.add_argument("--stats", default="results/data_stats.json")
    ap.add_argument("--max-seq-len", type=int, default=MAX_SEQ_LEN)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args(argv)

    import datasets  # noqa: PLC0415 - heavy imports only for the CLI
    import transformers  # noqa: PLC0415
    from transformers import AutoTokenizer  # noqa: PLC0415

    tok = AutoTokenizer.from_pretrained(BASE_MODEL, revision=BASE_MODEL_REVISION)

    def count_tokens(messages: list[dict[str, str]]) -> int:
        ids = tok.apply_chat_template(messages, tokenize=True, enable_thinking=False)
        if isinstance(ids, dict) or hasattr(ids, "keys"):  # BatchEncoding in newer transformers
            ids = ids["input_ids"]
        return len(ids)

    # Check that thinking-off rendering puts the empty think block where training expects it.
    probe = rag_messages("q?", ["x"]) + [{"role": "assistant", "content": "{}"}]
    rendered = tok.apply_chat_template(probe, tokenize=False, enable_thinking=False)
    prompt = tok.apply_chat_template(probe[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    from prompts import RESPONSE_MARKER  # noqa: PLC0415

    if not rendered.startswith(prompt) or RESPONSE_MARKER not in rendered:
        raise SystemExit("Chat template check failed: the thinking-off prompt is not a prefix of the training text")

    ds = datasets.load_dataset(SCIQ_DATASET, revision=SCIQ_REVISION)
    out_dir, stats_path = Path(args.out), Path(args.stats)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "dataset": SCIQ_DATASET,
        "dataset_revision": SCIQ_REVISION,
        "tokenizer": BASE_MODEL,
        "tokenizer_revision": BASE_MODEL_REVISION,
        "seed": args.seed,
        "max_seq_len": args.max_seq_len,
        "enable_thinking": False,
        "prompt_versions": PROMPT_VERSIONS,
        "library_versions": {"datasets": datasets.__version__, "transformers": transformers.__version__},
        "splits": {},
    }
    for split, plan in PLAN.items():
        rows = list(ds[split])
        items, dropped = clean_rows(rows)
        examples, summary = build_split(items, plan, split, count_tokens, args.max_seq_len, args.seed)
        path = out_dir / OUT_NAMES[split]
        with path.open("w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        report["splits"][split] = {
            "rows": len(rows),
            "dropped_empty_support": dropped,
            "usable_rows": len(items),
            "file": path.name,
            **summary,
        }
        print(f"{split}: {len(rows)} rows, {dropped} without support, wrote {len(examples)} -> {path}")
    stats_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"stats -> {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
