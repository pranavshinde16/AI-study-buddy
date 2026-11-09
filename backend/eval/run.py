"""Run the Phase 11 evaluation on a golden set.

    python -m eval.run --set golden_v1 --lecture-id <uuid> --generator all
    python -m eval.run --set golden_v1 --lecture-id <uuid> --generator cloud --limit 3   # smoke test

--generator   cloud | finetuned | base | all (= cloud,finetuned,base) | a comma list
--limit N     only the first N questions
--no-judge    skip the LLM judge (retrieval, refusals and latency only; no faithfulness/correctness)
--no-retrieval  skip the retrieval-only run (M6 + threshold report)

Free tier: every call goes through the app's Groq pacer (GROQ_TOKENS_PER_MINUTE), so a full run
can take a long time; progress is printed per question and every item is saved as it finishes.
The local models (finetuned/base) need Ollama running; each answer takes several seconds on CPU.
Results: eval_runs / eval_items (LLMOps page), and `python -m scripts.export_llmops`.
"""

import argparse
import json
import time

from eval._cli import lecture_uuid, safe_console, stamp

ALL = ("cloud", "finetuned", "base")


def _short(summary: dict) -> str:
    keys = ("n", "refusal_accuracy", "decision_accuracy", "faithfulness", "hallucination_rate",
            "correctness_answered", "correctness_all_answerable")
    parts = [f"{k}={summary.get(k)}" for k in keys if k in summary]
    lat = summary.get("latency") or {}
    if lat:
        parts.append(f"p50={lat.get('p50_ms')}ms p95={lat.get('p95_ms')}ms")
    if summary.get("errors"):
        parts.append(f"errors={summary['errors']}")
    return "  ".join(parts)


def main(argv: list[str] | None = None) -> int:
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", required=True)
    ap.add_argument("--lecture-id", required=True)
    ap.add_argument("--generator", default="cloud")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--no-retrieval", action="store_true")
    args = ap.parse_args(argv)

    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.models.lecture import Lecture
    from app.services.evaluation.golden import GoldenSetError, load_golden
    from app.services.evaluation.harness import EvalHarness, EvalSetupError
    from app.services.evaluation.judge import Judge
    from app.services.indexing import get_indexer
    from app.services.llm.client import get_llm_client
    from app.services.rag import get_rag_service

    settings = get_settings()
    lid = lecture_uuid(args.lecture_id)
    gens = list(ALL) if args.generator == "all" else [g.strip() for g in args.generator.split(",") if g.strip()]

    sf = get_session_factory()
    with sf() as db:
        lec = db.get(Lecture, lid)
        if lec is None:
            raise SystemExit(f"Lecture {lid} not found")
        duration = lec.duration_sec
    try:
        items, warnings = load_golden(args.set, duration_sec=duration)
    except GoldenSetError as exc:
        print(f"Golden set problem: {exc}")
        for p in exc.problems:
            print("  -", p)
        return 1
    for w in warnings:
        print("WARNING", w)
    if args.limit:
        items = items[: args.limit]

    judge = None if args.no_judge else Judge(settings, get_llm_client())
    print(f"Golden set {args.set}: {len(items)} questions; generators {gens}; "
          f"judge {'off' if judge is None else settings.eval_judge_provider + '/' + settings.eval_judge_model}; "
          f"RAG_MIN_SCORE {settings.rag_min_score}; top-k {settings.rag_top_k}")
    if settings.eval_judge_model == settings.llm_model and judge is not None:
        print("WARNING: EVAL_JUDGE_MODEL equals LLM_MODEL: the cloud generator would grade itself")

    harness = EvalHarness(settings, sf, get_rag_service(), get_indexer(), judge,
                          progress=lambda m: print(stamp(m), flush=True))
    t0 = time.perf_counter()
    try:
        res = harness.run(golden_set=args.set, items=items, lecture_id=lid, generators=gens,
                          retrieval=not args.no_retrieval)
    except EvalSetupError as exc:
        print("Cannot run:", exc)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted: finished items are saved; the current run is marked failed.")
        return 130

    print(f"\nDone in {time.perf_counter() - t0:.0f} s")
    if "retrieval" in res.summaries:
        r = res.summaries["retrieval"]
        print("Retrieval (shared):", json.dumps(r["retrieval"]))
        t = r["threshold"]
        print(f"RAG_MIN_SCORE {t['threshold']}: answerable min {t['answerable_min']}, "
              f"unanswerable max {t['unanswerable_max']}, gap {t['gap']}; "
              f"answerable refused by threshold {t['answerable'].get('wrongly_refused_by_threshold')}, "
              f"unanswerable refused by threshold {t['unanswerable'].get('refused_by_threshold')} "
              f"/ passed to the model {t['unanswerable'].get('passed_to_model')}")
        for kind, d in t["by_kind"].items():
            print(f"  {kind:<11} n={d['n']} min={d.get('min')} median={d.get('median')} max={d.get('max')} "
                  f"below={d['below_threshold']}")
    for g in gens:
        if g in res.summaries:
            print(f"{g}: {_short(res.summaries[g])}")
    print("Run ids:", {"retrieval": str(res.retrieval_run_id), **{k: str(v) for k, v in res.generator_runs.items()}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
