"""Print a lecture's retrieval chunks (and optionally its transcript segments) with their times,
to help write gold_start / gold_end by hand. Reads the database only; no model calls.

    python -m eval.segments --lecture-id <uuid>            # chunks (what retrieval sees)
    python -m eval.segments --lecture-id <uuid> --segments # every ASR segment
"""

import argparse

from sqlalchemy import select

from eval._cli import lecture_uuid, safe_console


def mmss(sec: float) -> str:
    return f"{int(sec // 60):02d}:{sec % 60:05.2f}"


def main(argv: list[str] | None = None) -> int:
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lecture-id", required=True)
    ap.add_argument("--segments", action="store_true", help="print ASR segments instead of chunks")
    args = ap.parse_args(argv)

    from app.db.session import get_session_factory
    from app.models.lecture import Chunk, Lecture, TranscriptSegment

    lid = lecture_uuid(args.lecture_id)
    with get_session_factory()() as db:
        lec = db.get(Lecture, lid)
        if lec is None:
            raise SystemExit(f"Lecture {lid} not found")
        print(f"{lec.title}  ({lec.duration_sec or 0:.1f} s)")
        if args.segments:
            for s in db.scalars(select(TranscriptSegment).where(TranscriptSegment.lecture_id == lid)
                                .order_by(TranscriptSegment.idx)):
                print(f"[{s.idx:>4}] {s.start_sec:8.2f}-{s.end_sec:8.2f} s  ({mmss(s.start_sec)})  {s.text.strip()}")
            return 0
        chunks = list(db.scalars(select(Chunk).where(Chunk.lecture_id == lid).order_by(Chunk.idx)))
        if not chunks:
            print("No chunks yet: ask one question in the app (or run eval.run) to index the lecture, "
                  "or use --segments.")
            return 0
        for c in chunks:
            print(f"\n=== chunk {c.idx}: {c.start_sec:.2f}-{c.end_sec:.2f} s ({mmss(c.start_sec)}-{mmss(c.end_sec)})")
            print(c.text.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
