import { useCallback, useEffect, useState } from "react";
import { Check, PartyPopper, RotateCw, X } from "lucide-react";

import { useReviewCard } from "@/api/hooks";
import type { FlashcardOut } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { FlipCard } from "./FlipCard";

/**
 * A review run over a snapshot of cards. "Knew it" removes the card from the queue;
 * "Didn't know" sends it to the back (the backend puts it in box 1, due now), so it comes
 * back in the same session, like the Leitner rules in docs/quizzes.md.
 */
export function ReviewSession({
  lectureId,
  initialCards,
  onFinish,
}: {
  lectureId: string;
  initialCards: FlashcardOut[];
  onFinish: () => void;
}) {
  const [queue, setQueue] = useState(initialCards);
  const [flipped, setFlipped] = useState(false);
  const [stats, setStats] = useState({ knew: 0, missed: 0 });
  const review = useReviewCard(lectureId);
  const card = queue[0];
  const doneCount = initialCards.length - new Set(queue.map((c) => c.id)).size;

  const answer = useCallback(
    (knew: boolean) => {
      if (!card || review.isPending) return;
      review.mutate(
        { cardId: card.id, knew },
        {
          onSuccess: (updated) => {
            setStats((s) => (knew ? { ...s, knew: s.knew + 1 } : { ...s, missed: s.missed + 1 }));
            setQueue((q) => (knew ? q.slice(1) : [...q.slice(1), updated]));
            setFlipped(false);
          },
        },
      );
    },
    [card, review],
  );

  // Keyboard: Space/Enter flip, → or K = knew it, ← or J = didn't know.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      if (e.key === " " || e.key === "Enter") {
        // A focused button already flips on Space/Enter; avoid flipping twice.
        if (target?.tagName === "BUTTON") return;
        e.preventDefault();
        setFlipped((f) => !f);
      } else if (e.key === "ArrowRight" || e.key.toLowerCase() === "k") {
        e.preventDefault();
        answer(true);
      } else if (e.key === "ArrowLeft" || e.key.toLowerCase() === "j") {
        e.preventDefault();
        answer(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [answer]);

  if (!card) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-2xl border bg-card px-6 py-12 text-center">
        <div className="flex size-12 items-center justify-center rounded-full bg-success/10 text-success">
          <PartyPopper className="size-6" />
        </div>
        <p className="font-medium">Session complete</p>
        <p className="text-sm text-muted-foreground">
          {initialCards.length} card{initialCards.length === 1 ? "" : "s"} reviewed · knew {stats.knew} · missed{" "}
          {stats.missed} (missed cards were shown again)
        </p>
        <Button onClick={onFinish}>
          <RotateCw /> Back to the deck
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium tabular-nums">
            {doneCount} / {initialCards.length} done
          </span>
          <span className="flex items-center gap-2">
            <Badge variant="outline">Box {card.box} of 5</Badge>
            <span className="text-muted-foreground tabular-nums">{queue.length} left</span>
          </span>
        </div>
        <Progress value={(doneCount / initialCards.length) * 100} label="Review progress" />
      </div>

      <FlipCard key={`${card.id}-${stats.knew + stats.missed}`} card={card} flipped={flipped} onFlip={() => setFlipped((f) => !f)} lectureId={lectureId} />

      <div className="grid grid-cols-2 gap-3">
        <Button variant="outline" size="lg" onClick={() => answer(false)} disabled={review.isPending}>
          <X className="text-destructive" /> Didn't know
        </Button>
        <Button size="lg" onClick={() => answer(true)} disabled={review.isPending}>
          <Check /> Knew it
        </Button>
      </div>
      <p className="hidden text-center text-xs text-muted-foreground sm:block">
        Shortcuts: <kbd className="rounded border px-1">Space</kbd> flip · <kbd className="rounded border px-1">←</kbd>/
        <kbd className="rounded border px-1">J</kbd> didn't know · <kbd className="rounded border px-1">→</kbd>/
        <kbd className="rounded border px-1">K</kbd> knew it
      </p>
      <div className="text-center">
        <Button variant="ghost" size="sm" onClick={onFinish}>
          End session
        </Button>
      </div>
    </div>
  );
}
