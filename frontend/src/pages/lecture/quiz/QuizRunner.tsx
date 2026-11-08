import { useState } from "react";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, Loader2, Send } from "lucide-react";

import type { AnswerValue, QuizOut } from "@/api/types";
import { SlowNotice } from "@/components/SlowNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { isAnswered, LETTERS, TYPE_LABELS } from "@/lib/quiz";
import { cn } from "@/lib/utils";

/** One question at a time; answers are kept here and sent together on submit. */
export function QuizRunner({
  quiz,
  submitting,
  slow,
  onSubmit,
  onQuit,
}: {
  quiz: QuizOut;
  submitting: boolean;
  slow: boolean;
  onSubmit: (answers: Record<string, AnswerValue>) => void;
  onQuit: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({});
  const q = quiz.questions[index];
  const total = quiz.questions.length;
  const last = index === total - 1;
  const answeredCount = quiz.questions.filter((x) => isAnswered(answers[x.id])).length;
  const unanswered = total - answeredCount;

  const set = (v: AnswerValue) => setAnswers((prev) => ({ ...prev, [q.id]: v }));

  return (
    <Card>
      <CardContent className="space-y-5 pt-6">
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="font-medium">
              Question {index + 1} of {total}
            </span>
            <span className="text-muted-foreground tabular-nums">{answeredCount} answered</span>
          </div>
          <Progress value={((index + 1) / total) * 100} label="Quiz progress" />
        </div>

        <div className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="secondary">{TYPE_LABELS[q.type]}</Badge>
            <Badge variant="outline">{q.difficulty}</Badge>
            {q.topic && <Badge>{q.topic}</Badge>}
          </div>
          <h2 className="text-lg font-semibold leading-snug" id={`q-${q.id}`}>
            {q.question}
          </h2>
        </div>

        {q.type === "mcq" && q.options && (
          <div role="radiogroup" aria-labelledby={`q-${q.id}`} className="grid gap-2">
            {q.options.map((opt, i) => {
              const selected = answers[q.id] === LETTERS[i];
              return (
                <button
                  key={i}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={submitting}
                  onClick={() => set(LETTERS[i])}
                  className={cn(
                    "flex items-start gap-3 rounded-xl border p-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected ? "border-primary bg-accent" : "hover:bg-muted",
                  )}
                >
                  <span
                    className={cn(
                      "flex size-6 shrink-0 items-center justify-center rounded-md border text-xs font-semibold",
                      selected && "border-primary bg-primary text-primary-foreground",
                    )}
                  >
                    {LETTERS[i]}
                  </span>
                  <span className="pt-0.5">{opt}</span>
                </button>
              );
            })}
          </div>
        )}

        {q.type === "true_false" && (
          <div role="radiogroup" aria-labelledby={`q-${q.id}`} className="grid grid-cols-2 gap-2">
            {[true, false].map((v) => {
              const selected = answers[q.id] === v;
              return (
                <button
                  key={String(v)}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={submitting}
                  onClick={() => set(v)}
                  className={cn(
                    "rounded-xl border p-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected ? "border-primary bg-accent" : "hover:bg-muted",
                  )}
                >
                  {v ? "True" : "False"}
                </button>
              );
            })}
          </div>
        )}

        {q.type === "short_answer" && (
          <textarea
            aria-labelledby={`q-${q.id}`}
            rows={4}
            maxLength={2000}
            placeholder="Type your answer in a sentence or two"
            disabled={submitting}
            value={(answers[q.id] as string | undefined) ?? ""}
            onChange={(e) => set(e.target.value)}
            className="w-full rounded-xl border border-input bg-card px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        )}

        {last && unanswered > 0 && !submitting && (
          <p className="flex items-center gap-2 text-sm text-warning">
            <AlertTriangle className="size-4" />
            {unanswered} unanswered question{unanswered === 1 ? "" : "s"} will count as wrong.
          </p>
        )}
        <SlowNotice show={slow}>
          Waiting for the free-tier rate limit… short answers are graded by the model, which can take up to a minute.
        </SlowNotice>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onQuit} disabled={submitting}>
            Quit
          </Button>
          <div className="ml-auto flex gap-2">
            <Button variant="outline" onClick={() => setIndex((i) => i - 1)} disabled={index === 0 || submitting}>
              <ArrowLeft /> Back
            </Button>
            {last ? (
              <Button onClick={() => onSubmit(answers)} disabled={submitting}>
                {submitting ? <Loader2 className="animate-spin" /> : <Send />}
                {submitting ? "Grading…" : "Submit"}
              </Button>
            ) : (
              <Button onClick={() => setIndex((i) => i + 1)}>
                {isAnswered(answers[q.id]) ? <Check /> : null}
                Next <ArrowRight />
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
