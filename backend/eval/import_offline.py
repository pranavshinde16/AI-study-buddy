"""Import the Phase 10 SciQ evaluation results (finetune/results/eval_hf.json and
eval_ollama_subset50.json) as "offline" eval runs. Safe to run twice (already imported = skipped).

    python -m eval.import_offline [--results-dir ../finetune/results]
"""

import argparse
from pathlib import Path

from eval._cli import safe_console


def main(argv: list[str] | None = None) -> int:
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", help="default: FINETUNE_RESULTS_DIR")
    args = ap.parse_args(argv)

    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.services.evaluation.offline import import_all

    results = Path(args.results_dir).resolve() if args.results_dir else get_settings().finetune_results_path
    with get_session_factory()() as db:
        out = import_all(db, results)
    print(f"Results dir: {results}")
    for name, n in out.items():
        print(f"  {name}: " + (n if isinstance(n, str) else f"{n} run(s) imported" if n else "already imported"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
