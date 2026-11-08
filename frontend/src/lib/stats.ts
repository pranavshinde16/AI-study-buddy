/**
 * Dashboard/analytics numbers computed in the browser from existing endpoints only
 * (GET /lectures, /lectures/{id}/quizzes, /lectures/{id}/flashcards). Nothing is estimated:
 * a value that needs Phase 9 data (mastery history, streaks) is not computed here.
 */
import type { DeckOut, LectureOut, QuizSummaryOut } from "@/api/types";

export interface QuizPoint {
  quizId: string;
  lectureId: string;
  lectureTitle: string;
  createdAt: string;
  difficulty: string | null;
  numQuestions: number;
  attempts: number;
  bestPercent: number | null;
}

/** Every quiz of every lecture, oldest first. */
export function flattenQuizzes(lectures: LectureOut[], quizLists: (QuizSummaryOut[] | undefined)[]): QuizPoint[] {
  const out: QuizPoint[] = [];
  lectures.forEach((l, i) => {
    for (const q of quizLists[i] ?? []) {
      out.push({
        quizId: q.quiz_id,
        lectureId: l.id,
        lectureTitle: l.title,
        createdAt: q.created_at,
        difficulty: q.difficulty,
        numQuestions: q.num_questions,
        attempts: q.attempts,
        bestPercent: q.best_percent,
      });
    }
  });
  return out.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

/** Mean of the best score of each quiz that was taken at least once; null if none. */
export function averageBest(points: QuizPoint[]): number | null {
  const taken = points.filter((p) => p.bestPercent !== null);
  if (!taken.length) return null;
  return taken.reduce((s, p) => s + (p.bestPercent as number), 0) / taken.length;
}

export function totalDue(decks: (DeckOut | undefined)[]): number {
  return decks.reduce((s, d) => s + (d?.due ?? 0), 0);
}

export interface RevisionRow {
  lectureId: string;
  lectureTitle: string;
  total: number;
  reviewed: number;
  dueNow: number;
}

/** Per lecture: cards in the deck, cards reviewed at least once, cards due now (full decks needed). */
export function revisionRows(lectures: LectureOut[], decks: (DeckOut | undefined)[]): RevisionRow[] {
  return lectures
    .map((l, i) => {
      const cards = decks[i]?.cards ?? [];
      return {
        lectureId: l.id,
        lectureTitle: l.title,
        total: cards.length,
        reviewed: cards.filter((c) => c.last_reviewed_at !== null).length,
        dueNow: cards.filter((c) => c.due).length,
      };
    })
    .filter((r) => r.total > 0);
}

/** Card count per Leitner box (1-5) over all decks. */
export function boxDistribution(decks: (DeckOut | undefined)[]): { box: string; cards: number }[] {
  const counts = [0, 0, 0, 0, 0];
  for (const d of decks) for (const c of d?.cards ?? []) if (c.box >= 1 && c.box <= 5) counts[c.box - 1] += 1;
  return counts.map((n, i) => ({ box: `Box ${i + 1}`, cards: n }));
}
