import { BarChart3, Layers, ListChecks, Radar, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";

import { useLectures, useLectureStats } from "@/api/hooks";
import { SimpleBarChart } from "@/components/charts/charts";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/format";
import { boxDistribution, flattenQuizzes, revisionRows } from "@/lib/stats";

export function AnalyticsPage() {
  const lectures = useLectures();
  const stats = useLectureStats(lectures.data, true);

  const header = (
    <header>
      <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
      <p className="mt-1 text-sm text-muted-foreground">Quiz history and flashcard revision across your lectures.</p>
    </header>
  );

  if (lectures.isError) {
    return (
      <section className="space-y-6">
        {header}
        <ErrorState error={lectures.error} onRetry={() => void lectures.refetch()} />
      </section>
    );
  }

  const list = lectures.data ?? [];
  const loading = lectures.isPending || stats.isPending;
  const points = flattenQuizzes(list, stats.quizzes.map((q) => q.data)).reverse(); // newest first
  const decks = stats.decks.map((d) => d.data);
  const revision = revisionRows(list, decks);
  const boxes = boxDistribution(decks);
  const totalCards = boxes.reduce((s, b) => s + b.cards, 0);

  return (
    <section className="space-y-6">
      {header}
      {stats.isError && (
        <p className="flex items-center gap-2 text-sm text-warning">
          <TriangleAlert className="size-4" /> Some lecture data couldn't be loaded; the figures below may be incomplete.
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Radar className="size-4 text-primary" /> Mastery by topic
          </CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={Radar}
            title="Coming with progress tracking (Phase 9)"
            description="Mastery is stored after every quiz submission; the chart needs the /progress endpoint added in Phase 9."
            className="border-0 py-6"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ListChecks className="size-4 text-primary" /> Quiz history
          </CardTitle>
          <CardDescription>Every quiz you generated, with your best score.</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-48 w-full" />
          ) : points.length === 0 ? (
            <EmptyState icon={ListChecks} title="No quizzes yet" description="Generate a quiz from any lecture's Quiz tab." className="border-0" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[32rem] text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-2 pr-3 font-medium">Lecture</th>
                    <th className="py-2 pr-3 font-medium">Created</th>
                    <th className="py-2 pr-3 font-medium">Difficulty</th>
                    <th className="py-2 pr-3 text-right font-medium">Questions</th>
                    <th className="py-2 pr-3 text-right font-medium">Attempts</th>
                    <th className="py-2 text-right font-medium">Best</th>
                  </tr>
                </thead>
                <tbody>
                  {points.map((p) => (
                    <tr key={p.quizId} className="border-b last:border-0">
                      <td className="max-w-[14rem] truncate py-2 pr-3">
                        <Link to={`/lectures/${p.lectureId}/quiz`} className="hover:text-primary hover:underline">
                          {p.lectureTitle}
                        </Link>
                      </td>
                      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">{formatDateTime(p.createdAt)}</td>
                      <td className="py-2 pr-3 capitalize">{p.difficulty ?? "–"}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{p.numQuestions}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{p.attempts}</td>
                      <td className="py-2 text-right font-medium tabular-nums">
                        {p.bestPercent === null ? "–" : `${Math.round(p.bestPercent)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers className="size-4 text-primary" /> Revision done vs pending
            </CardTitle>
            <CardDescription>Per deck: cards reviewed at least once, and cards due now.</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-40 w-full" />
            ) : revision.length === 0 ? (
              <EmptyState icon={Layers} title="No flashcard decks yet" description="Generate a deck in any lecture's Flashcards tab." className="border-0" />
            ) : (
              <ul className="space-y-4">
                {revision.map((r) => (
                  <li key={r.lectureId} className="space-y-1.5">
                    <div className="flex justify-between gap-2 text-sm">
                      <Link to={`/lectures/${r.lectureId}/flashcards`} className="min-w-0 truncate hover:text-primary hover:underline">
                        {r.lectureTitle}
                      </Link>
                      <span className="shrink-0 tabular-nums text-muted-foreground">
                        {r.reviewed}/{r.total} reviewed · {r.dueNow} due
                      </span>
                    </div>
                    <div
                      className="flex h-2 gap-0.5 overflow-hidden rounded-full bg-muted"
                      role="img"
                      aria-label={`${r.reviewed} of ${r.total} cards reviewed`}
                    >
                      <div className="h-full rounded-full bg-primary" style={{ width: `${(r.reviewed / r.total) * 100}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="size-4 text-primary" /> Cards per Leitner box
            </CardTitle>
            <CardDescription>Higher boxes are cards you know better (all decks).</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-56 w-full" />
            ) : totalCards === 0 ? (
              <EmptyState icon={BarChart3} title="No cards yet" className="border-0" />
            ) : (
              <>
                <SimpleBarChart
                  data={boxes}
                  xKey="box"
                  yKey="cards"
                  ariaLabel={`Cards per box: ${boxes.map((b) => `${b.box} ${b.cards}`).join(", ")}`}
                />
                <table className="sr-only">
                  <caption>Cards per Leitner box</caption>
                  <tbody>
                    {boxes.map((b) => (
                      <tr key={b.box}>
                        <th scope="row">{b.box}</th>
                        <td>{b.cards}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
