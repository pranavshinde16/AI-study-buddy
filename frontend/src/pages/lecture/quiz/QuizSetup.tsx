import { useState } from "react";
import { History, ListChecks, Loader2, RotateCw, Sparkles } from "lucide-react";

import type { DifficultyIn, GenerateQuizRequest, QuestionType, QuizSummaryOut } from "@/api/types";
import { Segmented } from "@/components/Segmented";
import { SlowNotice } from "@/components/SlowNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { config } from "@/config";
import { formatDateTime } from "@/lib/format";
import { TYPE_LABELS } from "@/lib/quiz";
import { cn } from "@/lib/utils";

const DIFFICULTIES: { value: DifficultyIn; label: string }[] = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
  { value: "mixed", label: "Mixed" },
];
const ALL_TYPES: QuestionType[] = ["mcq", "true_false", "short_answer"];

export function QuizSetup({
  topics,
  initialDifficulty,
  generating,
  slow,
  onGenerate,
  pastQuizzes,
  pastLoading,
  loadingQuizId,
  onRetake,
}: {
  topics: string[];
  initialDifficulty: DifficultyIn;
  generating: boolean;
  slow: boolean;
  onGenerate: (body: GenerateQuizRequest) => void;
  pastQuizzes: QuizSummaryOut[] | undefined;
  pastLoading: boolean;
  loadingQuizId: string | null;
  onRetake: (quizId: string) => void;
}) {
  const [num, setNum] = useState(Math.min(10, config.quizMaxQuestions));
  const [types, setTypes] = useState<QuestionType[]>(ALL_TYPES);
  const [difficulty, setDifficulty] = useState<DifficultyIn>(initialDifficulty);
  const [chosen, setChosen] = useState<string[]>([]);
  const [adaptive, setAdaptive] = useState(false);

  function toggleType(t: QuestionType) {
    setTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : ALL_TYPES.filter((x) => x === t || prev.includes(x))));
  }
  function toggleTopic(t: string) {
    setChosen((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));
  }

  const valid = types.length > 0 && num >= 1 && num <= config.quizMaxQuestions;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ListChecks className="size-4 text-primary" /> New quiz
          </CardTitle>
          <CardDescription>Questions are written only from this lecture's transcript.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-5"
            onSubmit={(e) => {
              e.preventDefault();
              if (!valid) return;
              onGenerate({
                num_questions: num,
                types,
                difficulty,
                topics: chosen.length ? chosen : null,
                adaptive: config.features.adaptiveQuiz && adaptive,
              });
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="num_questions">
                Number of questions: <span className="tabular-nums">{num}</span>
              </Label>
              <input
                id="num_questions"
                type="range"
                min={1}
                max={config.quizMaxQuestions}
                value={num}
                onChange={(e) => setNum(Number(e.target.value))}
                className="w-full accent-primary"
                disabled={generating}
              />
            </div>

            <fieldset className="space-y-2" disabled={generating}>
              <legend className="text-sm font-medium">Question types</legend>
              <div className="flex flex-wrap gap-2">
                {ALL_TYPES.map((t) => (
                  <label
                    key={t}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-sm transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                      types.includes(t) ? "border-primary bg-accent text-accent-foreground" : "hover:bg-muted",
                    )}
                  >
                    <input type="checkbox" className="accent-primary" checked={types.includes(t)} onChange={() => toggleType(t)} />
                    {TYPE_LABELS[t]}
                  </label>
                ))}
              </div>
              {types.length === 0 && <p className="text-xs text-destructive">Pick at least one type.</p>}
            </fieldset>

            <div className="space-y-2">
              <p className="text-sm font-medium">Difficulty</p>
              <Segmented label="Difficulty" value={difficulty} options={DIFFICULTIES} onChange={setDifficulty} />
            </div>

            {topics.length > 0 && (
              <fieldset className="space-y-2" disabled={generating}>
                <legend className="text-sm font-medium">
                  Topics <span className="font-normal text-muted-foreground">(none selected = all)</span>
                </legend>
                <div className="flex flex-wrap gap-2">
                  {topics.map((t) => (
                    <button
                      key={t}
                      type="button"
                      aria-pressed={chosen.includes(t)}
                      onClick={() => toggleTopic(t)}
                      className={cn(
                        "rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        chosen.includes(t) ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted",
                      )}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </fieldset>
            )}

            {config.features.adaptiveQuiz && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="accent-primary" checked={adaptive} onChange={(e) => setAdaptive(e.target.checked)} />
                Adaptive (focus on your weak topics)
              </label>
            )}

            <SlowNotice show={slow}>
              Waiting for the free-tier rate limit… generating questions can take up to a minute.
            </SlowNotice>

            <Button type="submit" disabled={!valid || generating} className="w-full sm:w-auto">
              {generating ? <Loader2 className="animate-spin" /> : <Sparkles />}
              {generating ? "Writing questions…" : "Generate quiz"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="size-4 text-primary" /> Earlier quizzes
          </CardTitle>
        </CardHeader>
        <CardContent>
          {pastLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : pastQuizzes?.length ? (
            <ul className="space-y-2" aria-label="Earlier quizzes">
              {pastQuizzes.map((q) => (
                <li key={q.quiz_id} className="flex items-center gap-2 rounded-xl border p-2.5">
                  <div className="min-w-0 flex-1 text-sm">
                    <p className="font-medium">
                      {q.num_questions} questions{q.difficulty ? ` · ${q.difficulty}` : ""}
                    </p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(q.created_at)}</p>
                  </div>
                  {q.best_percent !== null ? (
                    <Badge variant={q.best_percent >= 80 ? "success" : q.best_percent >= 50 ? "default" : "warning"}>
                      Best {Math.round(q.best_percent)}%
                    </Badge>
                  ) : (
                    <Badge variant="secondary">Not taken</Badge>
                  )}
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`Take the quiz from ${formatDateTime(q.created_at)} again`}
                    title="Take again"
                    disabled={loadingQuizId !== null || generating}
                    onClick={() => onRetake(q.quiz_id)}
                  >
                    {loadingQuizId === q.quiz_id ? <Loader2 className="animate-spin" /> : <RotateCw />}
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No quizzes yet. Your generated quizzes appear here.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
