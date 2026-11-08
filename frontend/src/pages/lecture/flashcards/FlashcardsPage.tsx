import { useState } from "react";
import { BookOpenText, CalendarCheck, Layers, Loader2, Play, RefreshCw, Sparkles } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { isApiError } from "@/api/client";
import { useDeck, useGenerateDeck } from "@/api/hooks";
import type { FlashcardOut } from "@/api/types";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Segmented } from "@/components/Segmented";
import { SlowNotice } from "@/components/SlowNotice";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { config } from "@/config";
import { useSlowFlag } from "@/hooks/useSlowFlag";
import { formatDateTime } from "@/lib/format";
import { notifySuccess } from "@/lib/notify";
import { ReviewSession } from "./ReviewSession";

type Mode = "due" | "all";

export function FlashcardsPage() {
  const { id = "" } = useParams();
  const deck = useDeck(id, false);
  const generate = useGenerateDeck(id);
  const slow = useSlowFlag(generate.isPending, config.slowRequestMs);
  const [mode, setMode] = useState<Mode>("due");
  const [session, setSession] = useState<{ n: number; cards: FlashcardOut[] } | null>(null);

  if (deck.isError) return <ErrorState error={deck.error} onRetry={() => void deck.refetch()} />;
  if (deck.isPending) return <DeckSkeleton />;

  const cards = deck.data.cards;
  const due = cards.filter((c) => c.due);

  if (session) {
    return (
      <ReviewSession
        key={session.n}
        lectureId={id}
        initialCards={session.cards}
        onFinish={() => {
          setSession(null);
          void deck.refetch();
        }}
      />
    );
  }

  const genError = generate.error;
  if (cards.length === 0) {
    const needsNotes = isApiError(genError, "NOTES_NOT_GENERATED") || isApiError(genError, "LECTURE_NOT_READY");
    return (
      <div className="space-y-4">
        <SlowNotice show={slow}>
          Waiting for the free-tier rate limit… writing a deck can take up to a minute.
        </SlowNotice>
        <EmptyState
          icon={needsNotes ? BookOpenText : Layers}
          title={needsNotes ? "Flashcards need the lecture's notes first" : "No flashcards yet"}
          description={
            needsNotes
              ? "Cards are built from the summary's definitions and the topic notes."
              : "Generate a deck of definition and concept cards from this lecture, then review them with spaced repetition."
          }
          action={
            needsNotes ? (
              <Button asChild variant="outline">
                <Link to={`/lectures/${id}/notes`}>Go to Summary & Notes</Link>
              </Button>
            ) : (
              <Button onClick={() => generate.mutate(false)} disabled={generate.isPending}>
                {generate.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
                {generate.isPending ? "Writing cards…" : "Generate flashcards"}
              </Button>
            )
          }
        />
      </div>
    );
  }

  const pool = mode === "due" ? due : cards;
  const boxes = [1, 2, 3, 4, 5].map((b) => cards.filter((c) => c.box === b).length);
  const nextDue = cards
    .filter((c) => !c.due)
    .map((c) => c.due_at)
    .sort()[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented
          label="Cards to review"
          value={mode}
          onChange={setMode}
          options={[
            { value: "due", label: `Due today (${due.length})` },
            { value: "all", label: `All cards (${cards.length})` },
          ]}
        />
        <ConfirmDialog
          title="Regenerate the deck?"
          description="This writes a new deck with the model and resets all review progress (every card goes back to box 1)."
          confirmLabel="Regenerate"
          onConfirm={() =>
            generate.mutate(true, { onSuccess: (d) => notifySuccess("New deck ready", `${d.total} cards.`) })
          }
          trigger={
            <Button variant="outline" size="sm" disabled={generate.isPending}>
              {generate.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              Regenerate deck
            </Button>
          }
        />
      </div>
      <SlowNotice show={slow}>Waiting for the free-tier rate limit… writing a deck can take up to a minute.</SlowNotice>

      <Card>
        <CardContent className="space-y-6 pt-6">
          {pool.length === 0 ? (
            <EmptyState
              icon={CalendarCheck}
              title="Nothing due right now"
              description={nextDue ? `The next card is due ${formatDateTime(nextDue)}.` : "All cards are reviewed."}
              action={
                <Button variant="outline" onClick={() => setMode("all")}>
                  Review all cards anyway
                </Button>
              }
              className="border-0"
            />
          ) : (
            <div className="flex flex-col items-center gap-3 py-6 text-center">
              <p className="text-4xl font-semibold tabular-nums">{pool.length}</p>
              <p className="text-sm text-muted-foreground">
                {mode === "due" ? "cards due for review" : "cards in the deck"}
              </p>
              <Button size="lg" onClick={() => setSession({ n: Date.now(), cards: pool })}>
                <Play /> Start review
              </Button>
            </div>
          )}

          <div>
            <p className="mb-2 text-sm font-medium">Leitner boxes</p>
            <div className="grid grid-cols-5 gap-2" role="list" aria-label="Cards per Leitner box">
              {boxes.map((n, i) => (
                <div key={i} role="listitem" className="rounded-xl border p-2 text-center">
                  <p className="text-lg font-semibold tabular-nums">{n}</p>
                  <p className="text-xs text-muted-foreground">Box {i + 1}</p>
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Knowing a card moves it up a box (due again in 1, 3, 7 or 14 days); missing it sends it back to box 1.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function DeckSkeleton() {
  return (
    <div className="space-y-4" aria-label="Loading flashcards">
      <Skeleton className="h-9 w-72" />
      <Skeleton className="h-80 rounded-2xl" />
    </div>
  );
}
