import type { ReactNode } from "react";
import { BookOpen, ChevronRight, Flame, Layers, LineChart, Target, TriangleAlert, Upload } from "lucide-react";
import { Link } from "react-router-dom";

import { ACTIVE_STATUSES, useLectures, useLectureStats } from "@/api/hooks";
import { PercentLineChart } from "@/components/charts/charts";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime, formatDuration } from "@/lib/format";
import { averageBest, flattenQuizzes, totalDue } from "@/lib/stats";

function Kpi({ icon: Icon, label, value, hint }: { icon: typeof BookOpen; label: string; value: ReactNode; hint: string }) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3 pt-6">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-foreground">
          <Icon className="size-5" />
        </div>
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold tabular-nums">{value}</p>
          <p className="text-xs text-muted-foreground">{hint}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function DashboardPage() {
  const lectures = useLectures();
  const stats = useLectureStats(lectures.data);

  const header = (
    <header>
      <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
      <p className="mt-1 text-sm text-muted-foreground">Your lectures, quiz scores and cards to review.</p>
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

  if (lectures.data && lectures.data.length === 0) {
    return (
      <section className="space-y-6">
        {header}
        <EmptyState
          icon={Upload}
          title="No lectures yet"
          description="Upload a recording to get a transcript, notes, quizzes, flashcards and a Q&A chat."
          action={
            <Button asChild>
              <Link to="/upload">
                <Upload /> Upload a lecture
              </Link>
            </Button>
          }
        />
      </section>
    );
  }

  const list = lectures.data ?? [];
  const loading = lectures.isPending || stats.isPending;
  const points = flattenQuizzes(list, stats.quizzes.map((q) => q.data));
  const taken = points.filter((p) => p.bestPercent !== null);
  const avg = averageBest(points);
  const due = totalDue(stats.decks.map((d) => d.data));
  const ready = list.filter((l) => l.status === "ready").length;

  return (
    <section className="space-y-6">
      {header}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {loading ? (
          Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28 rounded-2xl" />)
        ) : (
          <>
            <Kpi icon={BookOpen} label="Lectures" value={list.length} hint={`${ready} fully processed`} />
            <Kpi
              icon={Target}
              label="Average quiz score"
              value={avg === null ? "–" : `${Math.round(avg)}%`}
              hint={taken.length ? `best score of ${taken.length} taken quiz${taken.length === 1 ? "" : "zes"}` : "no quiz taken yet"}
            />
            <Kpi icon={Layers} label="Cards due" value={due} hint="flashcards due for review now" />
            <Kpi icon={Flame} label="Study streak" value="–" hint="arrives with progress tracking (Phase 9)" />
          </>
        )}
      </div>
      {stats.isError && (
        <p className="flex items-center gap-2 text-sm text-warning">
          <TriangleAlert className="size-4" /> Some quiz or flashcard data couldn't be loaded, so these numbers may be incomplete.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent lectures</CardTitle>
          </CardHeader>
          <CardContent>
            {lectures.isPending ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }, (_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : (
              <ul className="divide-y" aria-label="Recent lectures list">
                {list.slice(0, 6).map((l) => (
                  <li key={l.id}>
                    <Link
                      to={ACTIVE_STATUSES.has(l.status) ? `/lectures/${l.id}/processing` : `/lectures/${l.id}`}
                      className="flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{l.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {formatDuration(l.duration_sec)} · {formatDateTime(l.created_at)}
                        </p>
                      </div>
                      <StatusBadge status={l.status} error={l.error} />
                      <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Quiz score trend</CardTitle>
            <CardDescription>Best score of each quiz you've taken, in the order the quizzes were created.</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-64 w-full" />
            ) : taken.length === 0 ? (
              <EmptyState icon={LineChart} title="No quiz results yet" description="Take a quiz in any lecture to see your scores here." className="border-0" />
            ) : (
              <PercentLineChart
                ariaLabel={`Best quiz scores over time: ${taken.map((p) => `${Math.round(p.bestPercent!)}%`).join(", ")}`}
                data={taken.map((p) => ({
                  label: new Date(p.createdAt).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
                  value: p.bestPercent!,
                  detail: `${p.lectureTitle} · ${p.numQuestions} questions${p.difficulty ? ` · ${p.difficulty}` : ""}`,
                }))}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Weak topics</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={Target}
            title="Coming with progress tracking (Phase 9)"
            description="Topic mastery is updated every time you submit a quiz, and the quiz results already list the topics to revise. A cross-lecture view needs the /progress endpoint from Phase 9."
            className="border-0 py-6"
          />
        </CardContent>
      </Card>
    </section>
  );
}
