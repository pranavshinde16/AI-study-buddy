import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BookOpenText,
  Check,
  FileText,
  Loader2,
  RotateCw,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";

import type { LectureStatus } from "@/api/types";
import { keys, useLecture, useLectureStatus, useSummarize } from "@/api/hooks";
import { ErrorState } from "@/components/ErrorState";
import { SlowNotice } from "@/components/SlowNotice";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useSlowFlag } from "@/hooks/useSlowFlag";
import { notifySuccess } from "@/lib/notify";
import { STEPS, stepModel, type StepModel, type StepState } from "@/lib/processing";
import { cn } from "@/lib/utils";

function stepState(i: number, m: StepModel): StepState {
  if (i < m.current) return "done";
  if (i === m.current) return m.failed ? "failed" : "active";
  return "todo";
}

export function ProcessingPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const lecture = useLecture(id);
  const summarize = useSummarize(id);
  const status = useLectureStatus(id, summarize.isPending);
  const s = status.data;

  // Toast once when the lecture finishes while this page is open; refresh the lecture metadata.
  const prev = useRef<LectureStatus | null>(null);
  useEffect(() => {
    if (!s) return;
    if (prev.current && prev.current !== s.status) {
      void qc.invalidateQueries({ queryKey: keys.lecture(id), exact: true });
      void qc.invalidateQueries({ queryKey: keys.lectures });
      if (s.status === "ready") notifySuccess("Lecture ready", "Transcript, summary and notes are available.");
    }
    prev.current = s.status;
  }, [s, id, qc]);

  const slow = useSlowFlag(s?.status === "generating", 20_000);

  if (status.isError) {
    return (
      <section className="space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">Processing lecture</h1>
        <ErrorState error={status.error} onRetry={() => void status.refetch()} />
      </section>
    );
  }

  const model = s ? stepModel(s) : null;
  const transcriptReady = s && ["indexing", "transcribed", "generating", "ready"].includes(s.status);

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Processing</p>
        {lecture.data ? (
          <h1 className="truncate text-2xl font-semibold tracking-tight">{lecture.data.title}</h1>
        ) : (
          <Skeleton className="h-8 w-64" />
        )}
      </header>

      <Card>
        <CardContent className="space-y-6 pt-6">
          {!s || !model ? (
            <div className="space-y-4">
              <Skeleton className="h-2 w-full" />
              {STEPS.map((st) => (
                <Skeleton key={st.label} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <>
              <div className="space-y-2" aria-live="polite">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0 truncate text-muted-foreground">
                    {s.stage_detail ?? (model.failed ? "Stopped" : "Working…")}
                  </span>
                  <span className="shrink-0 font-medium tabular-nums">{s.progress}%</span>
                </div>
                <Progress
                  value={s.progress}
                  label="Processing progress"
                  className={cn(model.failed && "[&>div]:bg-destructive")}
                />
              </div>

              <ol className="space-y-1">
                {STEPS.map((step, i) => {
                  const state = stepState(i, model);
                  return (
                    <li key={step.label} className="flex gap-3" aria-current={state === "active" ? "step" : undefined}>
                      <div className="flex flex-col items-center">
                        <span
                          className={cn(
                            "flex size-8 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                            state === "done" && "border-success bg-success text-white",
                            state === "active" && "border-primary bg-accent text-primary",
                            state === "failed" && "border-destructive bg-destructive text-white",
                            state === "todo" && "border-border text-muted-foreground",
                          )}
                        >
                          {state === "done" && <Check className="size-4" />}
                          {state === "active" && <Loader2 className="size-4 animate-spin" />}
                          {state === "failed" && <X className="size-4" />}
                          {state === "todo" && <span className="text-xs font-medium">{i + 1}</span>}
                        </span>
                        {i < STEPS.length - 1 && (
                          <span className={cn("my-1 w-0.5 flex-1 rounded", i < model.current ? "bg-success" : "bg-border")} />
                        )}
                      </div>
                      <div className="pb-4 pt-1">
                        <p className={cn("text-sm font-medium", state === "todo" && "text-muted-foreground")}>
                          {step.label}
                          <span className="sr-only">: {state}</span>
                        </p>
                        <p className="text-xs text-muted-foreground">{step.hint}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>

              <SlowNotice show={slow}>
                Writing notes on the free tier: long lectures and rate-limit pauses can take a few minutes. Progress
                updates every 3 seconds.
              </SlowNotice>

              {s.status === "failed" && (
                <div role="alert" className="space-y-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4">
                  <p className="flex items-center gap-2 font-medium text-destructive">
                    <AlertTriangle className="size-4" /> Processing failed
                  </p>
                  <p className="text-sm text-muted-foreground">{s.error ?? "No error message was recorded."}</p>
                  <p className="text-sm text-muted-foreground">
                    A failed transcription can't be resumed. Upload the recording again to retry.
                  </p>
                  <Button asChild size="sm">
                    <Link to="/upload">
                      <Upload /> Upload again
                    </Link>
                  </Button>
                </div>
              )}

              {s.status === "transcribed" && s.error && (
                <div role="alert" className="space-y-3 rounded-xl border border-warning/30 bg-warning/10 p-4">
                  <p className="flex items-center gap-2 font-medium text-warning">
                    <AlertTriangle className="size-4" /> The transcript is ready, but the notes failed
                  </p>
                  <p className="text-sm text-muted-foreground">{s.error}</p>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => summarize.mutate(false)} disabled={summarize.isPending}>
                      {summarize.isPending ? <Loader2 className="animate-spin" /> : <RotateCw />}
                      Retry summary & notes
                    </Button>
                    <Button asChild size="sm" variant="outline">
                      <Link to={`/lectures/${id}/transcript`}>
                        <FileText /> Open transcript
                      </Link>
                    </Button>
                  </div>
                </div>
              )}

              {s.status === "transcribed" && !s.error && !summarize.isPending && (
                <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/40 p-4 text-sm">
                  <span className="mr-auto">
                    The transcript is ready. Notes start automatically when SUMMARY_AUTO is on.
                  </span>
                  <Button size="sm" variant="outline" onClick={() => summarize.mutate(false)}>
                    <Sparkles /> Generate notes now
                  </Button>
                </div>
              )}

              {s.status === "ready" && (
                <div className="flex flex-wrap items-center gap-2 rounded-xl border border-success/30 bg-success/10 p-4">
                  <p className="mr-auto flex items-center gap-2 font-medium text-success">
                    <Check className="size-4" /> All done
                  </p>
                  <Button asChild size="sm" variant="outline">
                    <Link to={`/lectures/${id}/transcript`}>
                      <FileText /> Transcript
                    </Link>
                  </Button>
                  <Button asChild size="sm">
                    <Link to={`/lectures/${id}/notes`}>
                      <BookOpenText /> Summary & notes
                    </Link>
                  </Button>
                </div>
              )}

              {transcriptReady && s.status !== "ready" && !(s.status === "transcribed") && (
                <p className="text-sm text-muted-foreground">
                  You can already{" "}
                  <Link to={`/lectures/${id}/transcript`} className="font-medium text-primary hover:underline">
                    read the transcript
                  </Link>{" "}
                  while the rest finishes.
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
