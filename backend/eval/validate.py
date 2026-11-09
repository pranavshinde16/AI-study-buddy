"""Check a golden-set file without calling any model.

    python -m eval.validate --set golden_v1                     # format only
    python -m eval.validate --set golden_v1 --lecture-id <uuid>  # + times inside the lecture
"""

import argparse
from collections import Counter

from eval._cli import lecture_uuid, safe_console
from app.services.evaluation.golden import GoldenSetError, golden_path, parse_golden


def main(argv: list[str] | None = None) -> int:
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", required=True, help="file name in eval/golden without .jsonl")
    ap.add_argument("--lecture-id", help="also check gold times against this lecture's length")
    args = ap.parse_args(argv)

    duration = None
    if args.lecture_id:
        from app.db.session import get_session_factory
        from app.models.lecture import Lecture

        with get_session_factory()() as db:
            lec = db.get(Lecture, lecture_uuid(args.lecture_id))
            if lec is None:
                raise SystemExit(f"Lecture {args.lecture_id} not found")
            duration = lec.duration_sec
            print(f"Lecture: {lec.title} ({duration or 0:.1f} s, status {lec.status})")

    try:
        path = golden_path(args.set)
    except GoldenSetError as exc:
        raise SystemExit(f"{exc}: {exc.problems}") from None
    if not path.is_file():
        raise SystemExit(f"Not found: {path}")
    items, problems, warnings = parse_golden(path.read_text(encoding="utf-8-sig"), duration_sec=duration)

    print(f"File: {path}")
    print(f"Questions: {len(items)}  answerable: {sum(i.answerable for i in items)}  "
          f"not answerable: {sum(not i.answerable for i in items)}")
    print("By kind:", dict(Counter(i.kind for i in items)))
    for w in warnings:
        print("WARNING", w)
    for p in problems:
        print("PROBLEM", p)
    print("OK" if not problems else f"{len(problems)} problem(s): fix them before running the eval")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
