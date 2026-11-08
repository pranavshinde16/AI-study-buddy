import { useState } from "react";
import { BookOpenText, Hourglass } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { useGenerateQuiz, useLoadQuiz, useNotes, useQuizzes, useSubmitQuiz } from "@/api/hooks";
import type { DifficultyIn, QuizOut, SubmitQuizResponse } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { config } from "@/config";
import { useSlowFlag } from "@/hooks/useSlowFlag";
import { notifySuccess } from "@/lib/notify";
import { buildAnswers } from "@/lib/quiz";
import { QuizResults } from "./QuizResults";
import { QuizRunner } from "./QuizRunner";
import { QuizSetup } from "./QuizSetup";

type Stage =
  | { kind: "setup" }
  | { kind: "taking"; quiz: QuizOut; attempt: number }
  | { kind: "results"; quiz: QuizOut; result: SubmitQuizResponse };

/** Quiz tab: setup → one question at a time → results with explanations. */
export function QuizPage() {
  const { id = "" } = useParams();
  const notes = useNotes(id);
  const quizzes = useQuizzes(id);
  const generate = useGenerateQuiz(id);
  const load = useLoadQuiz();
  const submit = useSubmitQuiz(id);
  const [stage, setStage] = useState<Stage>({ kind: "setup" });
  const [difficulty, setDifficulty] = useState<DifficultyIn>("medium");

  const genSlow = useSlowFlag(generate.isPending, config.slowRequestMs);
  const submitSlow = useSlowFlag(submit.isPending, config.slowRequestMs);

  const start = (quiz: QuizOut) => setStage((s) => ({ kind: "taking", quiz, attempt: (s.kind === "taking" ? s.attempt : 0) + 1 }));

  if (notes.isPending) return <QuizSkeleton />;
  if (notes.isError) {
    const code = notes.error.code;
    if (code === "NOTES_NOT_GENERATED" || code === "LECTURE_NOT_READY" || code === "GENERATION_IN_PROGRESS") {
      return (
        <EmptyState
          icon={code === "GENERATION_IN_PROGRESS" ? Hourglass : BookOpenText}
          title={code === "GENERATION_IN_PROGRESS" ? "Notes are being written" : "Quizzes need the lecture's notes first"}
          description="Questions are tagged with the topics from the Summary & Notes tab, so generate those first."
          action={
            <Button asChild variant="outline">
              <Link to={`/lectures/${id}/notes`}>Go to Summary & Notes</Link>
            </Button>
          }
        />
      );
    }
    return <ErrorState error={notes.error} onRetry={() => void notes.refetch()} />;
  }

  if (stage.kind === "taking") {
    return (
      <QuizRunner
        key={`${stage.quiz.quiz_id}-${stage.attempt}`}
        quiz={stage.quiz}
        submitting={submit.isPending}
        slow={submitSlow}
        onQuit={() => setStage({ kind: "setup" })}
        onSubmit={(answers) =>
          submit.mutate(
            { quizId: stage.quiz.quiz_id, body: { answers: buildAnswers(stage.quiz.questions, answers) } },
            { onSuccess: (result) => setStage({ kind: "results", quiz: stage.quiz, result }) },
          )
        }
      />
    );
  }

  if (stage.kind === "results") {
    return (
      <QuizResults
        lectureId={id}
        quiz={stage.quiz}
        result={stage.result}
        onRetake={() => start(stage.quiz)}
        onNew={(d) => {
          setDifficulty(d);
          setStage({ kind: "setup" });
        }}
      />
    );
  }

  return (
    <QuizSetup
      key={difficulty}
      topics={notes.data.topics.map((t) => t.title)}
      initialDifficulty={difficulty}
      generating={generate.isPending}
      slow={genSlow}
      pastQuizzes={quizzes.data}
      pastLoading={quizzes.isPending}
      loadingQuizId={load.isPending ? (load.variables ?? null) : null}
      onRetake={(quizId) => load.mutate(quizId, { onSuccess: start })}
      onGenerate={(body) =>
        generate.mutate(body, {
          onSuccess: (quiz) => {
            const m = quiz.meta;
            if (m.requested && m.generated !== null && m.generated < m.requested) {
              notifySuccess("Quiz ready", `${m.generated} of ${m.requested} questions passed validation.`);
            }
            start(quiz);
          },
        })
      }
    />
  );
}

function QuizSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_20rem]" aria-label="Loading quiz">
      <Skeleton className="h-96 rounded-2xl" />
      <Skeleton className="h-64 rounded-2xl" />
    </div>
  );
}
