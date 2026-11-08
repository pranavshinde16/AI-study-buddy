import type { FlashcardOut } from "@/api/types";
import { TimestampChip } from "@/components/TimestampChip";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** 3D flip card: question on the front, answer on the back. Click (or Space/Enter) flips it. */
export function FlipCard({
  card,
  flipped,
  onFlip,
  lectureId,
}: {
  card: FlashcardOut;
  flipped: boolean;
  onFlip: () => void;
  lectureId: string;
}) {
  const face =
    "absolute inset-0 flex flex-col rounded-2xl border bg-card p-6 shadow-sm [backface-visibility:hidden] [-webkit-backface-visibility:hidden]";
  return (
    <div className="[perspective:1200px]">
      <button
        type="button"
        onClick={onFlip}
        aria-label={flipped ? "Show the question" : "Show the answer"}
        aria-pressed={flipped}
        className="relative block h-72 w-full rounded-2xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:h-80"
      >
        <div
          className={cn(
            "relative h-full w-full transition-transform duration-500 [transform-style:preserve-3d] motion-reduce:transition-none",
            flipped && "[transform:rotateY(180deg)]",
          )}
        >
          <div className={face} aria-hidden={flipped}>
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="secondary">{card.kind === "definition" ? "Definition" : "Concept"}</Badge>
              {card.topic && <Badge>{card.topic}</Badge>}
            </div>
            <p className="m-auto max-w-prose text-center text-lg font-medium sm:text-xl">{card.front}</p>
            <p className="text-center text-xs text-muted-foreground">Click or press Space to flip</p>
          </div>
          <div className={cn(face, "[transform:rotateY(180deg)] bg-accent/40")} aria-hidden={!flipped}>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Answer</p>
            <p className="m-auto max-w-prose text-center text-base sm:text-lg">{card.back}</p>
          </div>
        </div>
      </button>
      {card.timestamp !== null && (
        <div className="mt-2 flex justify-center">
          <TimestampChip seconds={card.timestamp} lectureId={lectureId} />
        </div>
      )}
    </div>
  );
}
