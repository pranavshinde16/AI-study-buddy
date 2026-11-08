import { CheckCircle2, RotateCw, Sparkles, XCircle } from "lucide-react";

import type { Difficulty, QuizOut, SubmitQuizResponse } from "@/api/types";
import { TimestampChip } from "@/components/TimestampChip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { formatAnswer } from "@/lib/quiz";
import { cn } from "@/lib/utils";

const GRADED_BY: Record<SubmitQuizResponse["results"][number]["graded_by"], string> = {
  rule: "Auto-graded",
  llm: "Graded by the model",
  embedding: "Graded by similarity (model unavailable)",
};

export function QuizResults({
  lectureId,
  quiz,
  result,
  onRetake,
  onNew,
}: {
  lectureId: string;
  quiz: QuizOut;
  result: SubmitQuizResponse;
  onRetake: () => void;
  onNew: (difficulty: Difficulty) => void;
}) {
  const byId = new Map(quiz.questions.map((q) => [q.id, q]));
  const pct = Math.round(result.percent);

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-col gap-6 pt-6 sm:flex-row sm:items-center">
          <div className="text-center sm:w-40">
            <p className="text-5xl font-semibold tabular-nums tracking-tight">{pct}%</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {Number.isInteger(result.score) ? result.score : result.score.toFixed(1)} of {result.total} correct
            </p>
          </div>
          <div className="flex-1 space-y-3">
            <Progress value={result.percent} label="Score" />
            <p className="text-sm">
              Suggested next difficulty: <span className="font-medium capitalize">{result.suggested_next_difficulty}</span>
            </p>
            {result.weak_topics.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-sm">
                <span className="text-muted-foreground">Revise:</span>
                {result.weak_topics.map((t) => (
                  <Badge key={t} variant="warning">
                    {t}
                  </Badge>
                ))}
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => onNew(result.suggested_next_difficulty)}>
                <Sparkles /> New {result.suggested_next_difficulty} quiz
              </Button>
              <Button size="sm" variant="outline" onClick={onRetake}>
                <RotateCw /> Retake this quiz
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {result.topics.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Topic mastery after this attempt</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-3">
              {result.topics.map((t) => (
                <li key={t.topic} className="space-y-1">
                  <div className="flex justify-between gap-2 text-sm">
                    <span className="min-w-0 truncate">{t.topic}</span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      {Number.isInteger(t.correct) ? t.correct : t.correct.toFixed(1)}/{t.total} · mastery{" "}
                      {Math.round(t.mastery * 100)}%
                    </span>
                  </div>
                  <Progress value={t.mastery * 100} label={`Mastery of ${t.topic}`} />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Answers and explanations</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="space-y-3">
            {result.results.map((r, i) => {
              const q = byId.get(r.id);
              const partial = r.type === "short_answer" && r.score > 0 && r.score < 1;
              return (
                <li
                  key={r.id}
                  className={cn("space-y-2 rounded-xl border p-4", r.correct ? "border-success/30" : "border-destructive/30")}
                >
                  <div className="flex items-start gap-2">
                    {r.correct ? (
                      <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-label="Correct" />
                    ) : (
                      <XCircle className="mt-0.5 size-5 shrink-0 text-destructive" aria-label="Incorrect" />
                    )}
                    <p className="font-medium">
                      {i + 1}. {r.question}
                    </p>
                  </div>
                  <dl className="grid gap-1 pl-7 text-sm sm:grid-cols-[8rem_1fr]">
                    <dt className="text-muted-foreground">Your answer</dt>
                    <dd>{formatAnswer(r.your_answer, q)}</dd>
                    {!r.correct || r.type === "short_answer" ? (
                      <>
                        <dt className="text-muted-foreground">{r.type === "short_answer" ? "Model answer" : "Correct answer"}</dt>
                        <dd>{formatAnswer(r.correct_answer, q)}</dd>
                      </>
                    ) : null}
                  </dl>
                  {r.feedback && <p className="pl-7 text-sm text-muted-foreground">{r.feedback}</p>}
                  {r.explanation && <p className="pl-7 text-sm">{r.explanation}</p>}
                  <div className="flex flex-wrap items-center gap-2 pl-7 text-xs text-muted-foreground">
                    {r.timestamp !== null && <TimestampChip seconds={r.timestamp} lectureId={lectureId} />}
                    {r.topic && <Badge variant="secondary">{r.topic}</Badge>}
                    <span>{GRADED_BY[r.graded_by]}</span>
                    {partial && <span>· partial credit {Math.round(r.score * 100)}%</span>}
                  </div>
                </li>
              );
            })}
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}
