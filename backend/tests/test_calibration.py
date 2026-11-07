"""The RAG_MIN_SCORE proposal in scripts/calibrate_rag.py is computed only from the scores given."""

from app.core.config import Settings
from scripts.calibrate_rag import propose


def test_rag_min_score_default():
    """0.50: judgement call from the Phase 7 calibration (on-topic min 0.580, off-topic median 0.487),
    documented in docs/rag.md §3; re-check in Phase 11."""
    assert Settings(_env_file=None).rag_min_score == 0.50


def test_separated_groups_use_the_midpoint_of_the_gap():
    p = propose(on=[0.80, 0.70, 0.60], off=[0.30, 0.50])
    assert p == {"threshold": 0.55, "method": "midpoint_of_gap", "gap": 0.1, "on_refused": 0, "off_answered": 0}


def test_overlapping_groups_use_best_balanced_accuracy_and_lower_ties():
    p = propose(on=[0.80, 0.70, 0.45], off=[0.50, 0.40, 0.30])
    assert p["method"].startswith("best_balanced_accuracy")
    # 0.425 (all on-topic kept, one off-topic through) ties with 0.6 (one on-topic refused, no
    # off-topic through) at 0.833; the lower one wins because the answer prompt can still refuse.
    assert p["balanced_accuracy"] == round((1 + 2 / 3) / 2, 3)
    assert p["threshold"] == 0.425 and p["on_refused"] == 0 and p["off_answered"] == 1
