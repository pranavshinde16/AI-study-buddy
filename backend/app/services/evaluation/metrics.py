"""Pure metric functions for the eval harness (no DB, no model calls), so they are easy to test.

Retrieval (M6), per answerable question with a gold time range [gold_start, gold_end]:
    relevant chunk     its [start, end] overlaps the gold range (both ends inclusive)
    Hit@k              1 if a relevant chunk is among the top k, else 0
    reciprocal rank    1 / rank of the first relevant chunk (0 if none) -> mean = MRR
    context precision  relevant chunks / retrieved chunks (in the top k)
    average precision  mean of precision@i over the ranks i that hold a relevant chunk
                       (rank-weighted context precision, as in RAGAS); 0 if none relevant

Refusals (M8): a question is "refused" when the app answered answerable=false, either by the
threshold (below_threshold, no LLM call) or by the model (not_in_chunks).

Faithfulness (M7): supported claims / total claims of an answered question (judge output).
Hallucination rate: share of judged answers with faithfulness below 1.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.services.llmops import latency_stats, percentile


@dataclass(frozen=True)
class Span:
    start: float
    end: float


def overlaps(chunk: Span, gold: Span) -> bool:
    return chunk.start <= gold.end and chunk.end >= gold.start


def retrieval_item_metrics(chunks: Sequence[Span], gold: Span, ks: Sequence[int]) -> dict[str, Any]:
    rel = [overlaps(c, gold) for c in chunks]
    first = next((i + 1 for i, r in enumerate(rel) if r), None)
    hits_so_far, precisions = 0, []
    for i, r in enumerate(rel, start=1):
        if r:
            hits_so_far += 1
            precisions.append(hits_so_far / i)
    return {
        "relevant_ranks": [i + 1 for i, r in enumerate(rel) if r],
        "first_relevant_rank": first,
        **{f"hit@{k}": int(first is not None and first <= k) for k in ks},
        "reciprocal_rank": round(1.0 / first, 4) if first else 0.0,
        "context_precision": round(sum(rel) / len(rel), 4) if rel else 0.0,
        "average_precision": round(sum(precisions) / len(precisions), 4) if precisions else 0.0,
    }


def mean(values: Sequence[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def aggregate_retrieval(items: Sequence[dict[str, Any]], ks: Sequence[int]) -> dict[str, Any]:
    """items: retrieval_item_metrics() outputs of the answerable questions."""
    return {
        "n": len(items),
        **{f"hit@{k}": mean([i[f"hit@{k}"] for i in items]) for k in ks},
        "mrr": mean([i["reciprocal_rank"] for i in items]),
        "context_precision": mean([i["context_precision"] for i in items]),
        "average_precision": mean([i["average_precision"] for i in items]),
    }


def score_distribution(scores: Sequence[float]) -> dict[str, Any]:
    vals = sorted(scores)
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "min": round(vals[0], 4), "q1": round(percentile(vals, 25), 4),
            "median": round(percentile(vals, 50), 4), "q3": round(percentile(vals, 75), 4),
            "max": round(vals[-1], 4), "mean": round(sum(vals) / len(vals), 4)}


def threshold_report(rows: Sequence[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """rows: {"id", "kind", "answerable", "top_score"} for every golden question.
    Reports the score distribution per kind and what the CURRENT threshold does with them.
    It does not propose or change the threshold (that stays a human decision)."""
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("top_score") is not None:
            by_kind.setdefault(r["kind"], []).append(r)
    kinds = {}
    for kind, rs in sorted(by_kind.items()):
        below = [r for r in rs if r["top_score"] < threshold]
        kinds[kind] = {
            **score_distribution([r["top_score"] for r in rs]),
            "below_threshold": len(below),
            "at_or_above_threshold": len(rs) - len(below),
            "below_ids": [r["id"] for r in below],
        }
    answerable = [r["top_score"] for r in rows if r["answerable"] and r.get("top_score") is not None]
    unanswerable = [r["top_score"] for r in rows if not r["answerable"] and r.get("top_score") is not None]
    lo_ans = min(answerable) if answerable else None
    hi_un = max(unanswerable) if unanswerable else None
    return {
        "threshold": threshold,
        "by_kind": kinds,
        "answerable": {**score_distribution(answerable),
                       "wrongly_refused_by_threshold": sum(s < threshold for s in answerable)},
        "unanswerable": {**score_distribution(unanswerable),
                         "refused_by_threshold": sum(s < threshold for s in unanswerable),
                         "passed_to_model": sum(s >= threshold for s in unanswerable)},
        "separable": None if lo_ans is None or hi_un is None else lo_ans > hi_un,
        "gap": None if lo_ans is None or hi_un is None else round(lo_ans - hi_un, 4),
        "answerable_min": None if lo_ans is None else round(lo_ans, 4),
        "unanswerable_max": None if hi_un is None else round(hi_un, 4),
    }


def _refusal_block(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    n = len(items)
    thr = sum(i["refusal_reason"] == "below_threshold" for i in items)
    mod = sum(i["refusal_reason"] == "not_in_chunks" for i in items)
    return {"n": n, "refused": thr + mod, "by_threshold": thr, "by_model": mod,
            "rate": round((thr + mod) / n, 4) if n else None,
            "by_threshold_rate": round(thr / n, 4) if n else None,
            "by_model_rate": round(mod / n, 4) if n else None}


def aggregate_generation(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """items (status ok only): {"answerable" (gold), "kind", "predicted_answerable", "refusal_reason",
    "latency_ms", "faithfulness", "claims_total", "correctness"}."""
    gold_yes = [i for i in items if i["answerable"]]
    gold_no = [i for i in items if not i["answerable"]]
    answered = [i for i in items if i["predicted_answerable"]]
    judged = [i for i in answered if i.get("faithfulness") is not None]
    correct_decisions = sum(i["answerable"] == bool(i["predicted_answerable"]) for i in items)
    corr = [i.get("correctness") for i in gold_yes if i["predicted_answerable"]]
    return {
        "n": len(items),
        # M8: should refuse -> refused?
        "refusal_accuracy": _refusal_block(gold_no)["rate"],
        "refusal": {
            "unanswerable": _refusal_block(gold_no),
            "by_kind": {k: _refusal_block([i for i in gold_no if i["kind"] == k])
                        for k in sorted({i["kind"] for i in gold_no})},
            "false_refusals": _refusal_block(gold_yes),  # answerable but refused
        },
        "decision_accuracy": round(correct_decisions / len(items), 4) if items else None,
        "answered": len(answered),
        "answered_unanswerable": sum(not i["answerable"] for i in answered),
        # M7
        "faithfulness": mean([i["faithfulness"] for i in judged]),
        "hallucination_rate": round(sum(i["faithfulness"] < 1 for i in judged) / len(judged), 4) if judged else None,
        "judged_answers": len(judged),
        "answers_without_claims": sum(i.get("claims_total") == 0 for i in answered),
        # correctness against the reference answer
        "correctness_answered": mean(corr),  # mean judge score over answered answerable questions
        "correctness_all_answerable": (round(sum(c or 0 for c in corr) / len(gold_yes), 4) if gold_yes else None),
        "correctness_judged": sum(c is not None for c in corr),
        "latency": latency_stats([i["latency_ms"] for i in items]),
        "latency_answered": latency_stats([i["latency_ms"] for i in answered]),
    }
