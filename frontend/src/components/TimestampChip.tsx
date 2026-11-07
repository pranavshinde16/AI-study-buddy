import { Clock } from "lucide-react";
import { Link } from "react-router-dom";

import { formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A clickable time (from transcript segments). With `onSeek` it seeks the player directly;
 * otherwise it links to the lecture's transcript at that time (?t=seconds).
 */
export function TimestampChip({
  seconds,
  end,
  lectureId,
  onSeek,
  className,
}: {
  seconds: number;
  end?: number;
  lectureId?: string;
  onSeek?: (s: number) => void;
  className?: string;
}) {
  const label = end !== undefined ? `${formatTimestamp(seconds)}–${formatTimestamp(end)}` : formatTimestamp(seconds);
  const cls = cn(
    "inline-flex items-center gap-1 rounded-md bg-accent px-1.5 py-0.5 font-mono text-xs font-medium text-accent-foreground tabular-nums transition-colors hover:bg-primary hover:text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
    className,
  );
  const title = `Play from ${formatTimestamp(seconds)}`;
  if (onSeek) {
    return (
      <button type="button" className={cls} onClick={() => onSeek(seconds)} aria-label={title} title={title}>
        <Clock className="size-3" />
        {label}
      </button>
    );
  }
  return (
    <Link to={`/lectures/${lectureId}/transcript?t=${Math.floor(seconds)}`} className={cls} aria-label={title} title={title}>
      <Clock className="size-3" />
      {label}
    </Link>
  );
}
