"""Evaluation metrics (pure Python, no downloads), used by evaluate.py and the notebook.

- accuracy        : grounded-QA items answered (answerable=true) with the correct SciQ answer in
                    the answer text (normalised whole-word containment).
- token F1        : SQuAD-style token overlap between the predicted answer and the reference answer
                    (the training target: correct answer + supporting sentence from SciQ).
- ROUGE-L         : F-measure of the longest common token subsequence, same pair.
- refusal P/R/F1  : positive class = "should refuse" over grounded-QA + refusal items;
                    predicted refusal = answerable=false (or refusal wording if the JSON is invalid).
- JSON validity   : the output parses and matches the expected shape (RagAnswerOut / MCQ).
- MCQ answer match: the option marked correct is the SciQ correct answer (derived from data).
"""

from __future__ import annotations

import json
import re
import statistics
import string
from collections import Counter
from typing import Any

_ARTICLES = re.compile(r"\b(a|an|the)\b")
_CITE = re.compile(r"\[\s*C\d+\s*\]", re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_REFUSAL_WORDS = re.compile(
    r"(doesn't cover|does not cover|not covered|don't contain|do not contain|does not contain|"
    r"doesn't contain|cannot answer|can't answer|not in the (excerpts|lecture|context))",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    text = text.lower()
    text = "".join(ch if ch not in string.punctuation else " " for ch in text)
    text = _ARTICLES.sub(" ", text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def strip_citations(text: str) -> str:
    return " ".join(_CITE.sub(" ", text).split())


def contains_answer(prediction: str, answer: str) -> bool:
    """Normalised answer appears in the prediction as whole words."""
    p, a = normalize(prediction), normalize(answer)
    if not a:
        return False
    return re.search(rf"(^| ){re.escape(a)}( |$)", p) is not None


def token_f1(prediction: str, reference: str) -> float:
    p, r = tokens(prediction), tokens(reference)
    if not p or not r:
        return float(p == r)
    common = Counter(p) & Counter(r)
    same = sum(common.values())
    if same == 0:
        return 0.0
    precision, recall = same / len(p), same / len(r)
    return 2 * precision * recall / (precision + recall)


def _lcs(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def rouge_l(prediction: str, reference: str) -> float:
    p, r = tokens(prediction), tokens(reference)
    lcs = _lcs(p, r)
    if lcs == 0:
        return 0.0
    precision, recall = lcs / len(p), lcs / len(r)
    return 2 * precision * recall / (precision + recall)


def parse_json(text: str) -> Any | None:
    """Like the app's client: drop <think> blocks and ``` fences, then parse; tolerate prose around one object."""
    t = _THINK.sub("", text or "").strip()
    m = _FENCE.match(t)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(t[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def parse_rag(text: str) -> dict[str, Any] | None:
    """A valid RagAnswerOut: {"answerable": bool, "answer": str, "citations"?: [str]}."""
    d = parse_json(text)
    if not isinstance(d, dict) or not isinstance(d.get("answerable"), bool) or not isinstance(d.get("answer"), str):
        return None
    cites = d.get("citations", [])
    if not isinstance(cites, list) or not all(isinstance(c, str) for c in cites):
        return None
    return {"answerable": d["answerable"], "answer": d["answer"], "citations": cites}


def parse_mcq(text: str) -> dict[str, Any] | None:
    d = parse_json(text)
    if not isinstance(d, dict):
        return None
    q, opts, ans = d.get("question"), d.get("options"), d.get("answer")
    if not isinstance(q, str) or not q.strip():
        return None
    if not isinstance(opts, list) or len(opts) != 4 or not all(isinstance(o, str) and o.strip() for o in opts):
        return None
    if len({normalize(o) for o in opts}) != 4:
        return None
    if not isinstance(ans, str) or ans.strip().upper().rstrip(")") not in ("A", "B", "C", "D"):
        return None
    return {"question": q, "options": opts, "answer": ans.strip().upper().rstrip(")")}


def predicted_refusal(raw: str, parsed: dict[str, Any] | None) -> bool:
    if parsed is not None:
        return parsed["answerable"] is False
    return bool(_REFUSAL_WORDS.search(raw or ""))


# --- MCQ secondary checks (added after the first results; see rescore_mcq.py) ---------------------------
_OPTION_LABEL = re.compile(r"^\s*\(?[A-Da-d][.):]\s+")


def strip_option_label(option: str) -> str:
    """'B. It releases energy.' -> 'It releases energy.' (some models put the letter into the option text)."""
    return _OPTION_LABEL.sub("", option, count=1)


def mcq_loose_match(chosen: str, correct: str) -> bool:
    """Looser than answer_matches_source: label stripped, and either text contains the other as whole words."""
    c = strip_option_label(chosen)
    return contains_answer(c, correct) or contains_answer(correct, c)


def _mean(xs: list[float]) -> float | None:
    return round(statistics.fmean(xs), 4) if xs else None


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return round(s[k], 1)


def score_items(items: list[dict[str, Any]], outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """`items` from prepare_data (task, meta); `outputs` = [{"text", "latency_ms"}] in the same order."""
    if len(items) != len(outputs):
        raise ValueError("items and outputs differ in length")
    gqa_acc, gqa_f1, gqa_rouge, gqa_valid, gqa_cite = [], [], [], [], []
    tp = fp = fn = tn = 0
    rag_valid = []
    mcq_valid, mcq_match = [], []
    latencies = [float(o["latency_ms"]) for o in outputs if o.get("latency_ms") is not None]
    per_item = []

    for item, out in zip(items, outputs):
        task, meta, raw = item["task"], item["meta"], out.get("text", "")
        row: dict[str, Any] = {"id": item["id"], "task": task}
        if task in ("gqa", "refusal"):
            parsed = parse_rag(raw)
            rag_valid.append(parsed is not None)
            refused = predicted_refusal(raw, parsed)
            should_refuse = task == "refusal"
            tp += should_refuse and refused
            fp += (not should_refuse) and refused
            fn += should_refuse and not refused
            tn += (not should_refuse) and not refused
            row.update(json_valid=parsed is not None, refused=refused)
            if task == "gqa":
                answer = strip_citations(parsed["answer"]) if parsed else strip_citations(raw)
                correct = bool(parsed and parsed["answerable"] and contains_answer(answer, meta["correct_answer"]))
                f1 = token_f1(answer, meta["reference_answer"]) if parsed else 0.0
                rl = rouge_l(answer, meta["reference_answer"]) if parsed else 0.0
                cited = bool(parsed and meta["gold_citation"] in parsed["citations"])
                gqa_acc.append(float(correct))
                gqa_f1.append(f1)
                gqa_rouge.append(rl)
                gqa_valid.append(parsed is not None)
                gqa_cite.append(float(cited))
                row.update(correct=correct, f1=round(f1, 4), rouge_l=round(rl, 4), cited_gold=cited)
        elif task == "mcq":
            parsed = parse_mcq(raw)
            match = False
            if parsed:
                chosen = parsed["options"][("A", "B", "C", "D").index(parsed["answer"])]
                match = normalize(chosen) == normalize(meta["correct_answer"])
            mcq_valid.append(parsed is not None)
            mcq_match.append(match)
            row.update(json_valid=parsed is not None, answer_matches_source=match)
        per_item.append(row)

    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if precision is not None and recall is not None else None)
    summary = {
        "n_items": len(items),
        "gqa": {
            "n": len(gqa_acc),
            "accuracy": _mean(gqa_acc),
            "token_f1": _mean(gqa_f1),
            "rouge_l": _mean(gqa_rouge),
            "json_valid_rate": _mean([float(v) for v in gqa_valid]),
            "gold_citation_rate": _mean(gqa_cite),
        },
        "refusal": {
            "n_should_refuse": tp + fn,
            "n_should_answer": fp + tn,
            "precision": None if precision is None else round(precision, 4),
            "recall": None if recall is None else round(recall, 4),
            "f1": None if f1 is None else round(f1, 4),
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        },
        "rag_json_valid_rate": _mean([float(v) for v in rag_valid]),
        "mcq": {
            "n": len(mcq_valid),
            "json_valid_rate": _mean([float(v) for v in mcq_valid]),
            "answer_matches_source_rate": _mean([float(v) for v in mcq_match]),
        },
        "latency_ms": {"mean": _mean(latencies), "p50": _pct(latencies, 0.5), "p95": _pct(latencies, 0.95), "n": len(latencies)},
    }
    return {"summary": summary, "per_item": per_item}
