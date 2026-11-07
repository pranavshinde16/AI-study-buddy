import { useState } from "react";
import {
  BookOpenText,
  ChevronDown,
  Copy,
  FileDown,
  Hourglass,
  Lightbulb,
  ListChecks,
  Loader2,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { TRANSCRIPT_STATUSES, useLecture, useLectureStatus, useSummarize, useSummary } from "@/api/hooks";
import type { SummaryResponse, TopicOut } from "@/api/types";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Markdown } from "@/components/Markdown";
import { SlowNotice } from "@/components/SlowNotice";
import { TimestampChip } from "@/components/TimestampChip";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useSlowFlag } from "@/hooks/useSlowFlag";
import { safeFilename, saveText } from "@/lib/download";
import { formatDateTime } from "@/lib/format";
import { notifyError, notifySuccess } from "@/lib/notify";
import { summaryToMarkdown } from "@/lib/summaryMarkdown";
import { cn } from "@/lib/utils";

export function NotesPage() {
  const { id = "" } = useParams();
  const lecture = useLecture(id);
  const summarize = useSummarize(id);
  const status = useLectureStatus(id, summarize.isPending);
  const current = status.data?.status ?? lecture.data?.status;
  const summary = useSummary(id, current === "ready");
  const slow = useSlowFlag(summarize.isPending || current === "generating", 8000);
  const title = lecture.data?.title ?? "Lecture";

  if (lecture.isError) return <ErrorState error={lecture.error} onRetry={() => void lecture.refetch()} />;
  if (!current) return <NotesSkeleton />;

  // A summary we already have (just generated, or cached) wins over the status checks below.
  const data = summary.data ?? summarize.data;

  if (!data) {
    if (summarize.isPending || current === "generating") {
      return (
        <div className="space-y-4">
          <SlowNotice show={slow}>
            Waiting for the free-tier rate limit… writing notes for a long lecture can take a few minutes.
          </SlowNotice>
          <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <Loader2 className="size-4 animate-spin" />
            {status.data?.stage_detail ?? "Writing the summary and notes…"}
          </p>
          <NotesSkeleton />
        </div>
      );
    }
    if (current === "failed" || !TRANSCRIPT_STATUSES.has(current)) {
      return (
        <EmptyState
          icon={current === "failed" ? X : Hourglass}
          title={current === "failed" ? "Processing failed" : "The transcript isn't ready yet"}
          description="Notes are written from the transcript, so they come after transcription."
          action={
            <Button asChild variant="outline">
              <Link to={`/lectures/${id}/processing`}>View progress</Link>
            </Button>
          }
        />
      );
    }
    if (current === "ready" && summary.isPending) return <NotesSkeleton />;
    if (current === "ready" && summary.isError) {
      return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />;
    }
    // transcribed (maybe with a failed summary): offer to generate.
    return (
      <EmptyState
        icon={Sparkles}
        title="No summary yet"
        description={
          <>
            <p>Generate a summary, key takeaways, a glossary and topic notes from the transcript.</p>
            {status.data?.error && <p className="mt-2 text-destructive">Last attempt failed: {status.data.error}</p>}
          </>
        }
        action={
          <Button onClick={() => summarize.mutate(false)}>
            <Sparkles /> Generate summary & notes
          </Button>
        }
      />
    );
  }

  return (
    <SummaryView
      lectureId={id}
      title={title}
      data={data}
      regenerating={summarize.isPending}
      slow={slow}
      onRegenerate={() => summarize.mutate(true)}
    />
  );
}

function SummaryView({
  lectureId,
  title,
  data,
  regenerating,
  slow,
  onRegenerate,
}: {
  lectureId: string;
  title: string;
  data: SummaryResponse;
  regenerating: boolean;
  slow: boolean;
  onRegenerate: () => void;
}) {
  const [open, setOpen] = useState<Set<number>>(() => new Set(data.topics.length ? [0] : []));
  const allOpen = data.topics.length > 0 && open.size === data.topics.length;

  async function copyMarkdown() {
    try {
      await navigator.clipboard.writeText(summaryToMarkdown(title, data));
      notifySuccess("Copied as Markdown");
    } catch (err) {
      notifyError(err, "Couldn't copy to the clipboard");
    }
  }

  function exportMarkdown() {
    const name = safeFilename(title, "md");
    saveText(summaryToMarkdown(title, data), name);
    notifySuccess("Exported", name);
  }

  function toggle(i: number) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  const m = data.meta;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="outline" size="sm" onClick={() => void copyMarkdown()}>
          <Copy /> Copy Markdown
        </Button>
        <Button variant="outline" size="sm" onClick={exportMarkdown}>
          <FileDown /> Export .md
        </Button>
        <ConfirmDialog
          title="Regenerate the summary and notes?"
          description="This runs the model again on the free tier and replaces the current summary, takeaways, definitions and topic notes. It can take a few minutes."
          confirmLabel="Regenerate"
          onConfirm={onRegenerate}
          trigger={
            <Button size="sm" disabled={regenerating}>
              {regenerating ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              {regenerating ? "Regenerating…" : "Regenerate"}
            </Button>
          }
        />
      </div>
      <SlowNotice show={regenerating && slow}>
        Waiting for the free-tier rate limit… the current notes stay visible until the new ones arrive.
      </SlowNotice>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpenText className="size-4 text-primary" /> Summary
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-relaxed whitespace-pre-line">{data.summary}</p>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Lightbulb className="size-4 text-warning" /> Key takeaways
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.key_takeaways.length ? (
              <ul className="space-y-2">
                {data.key_takeaways.map((t, i) => (
                  <li key={i} className="flex gap-2 text-sm">
                    <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
                    <span>{t}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No takeaways were extracted.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ListChecks className="size-4 text-success" /> Definitions
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.definitions.length ? (
              <dl className="space-y-3">
                {data.definitions.map((d, i) => (
                  <div key={i} className="text-sm">
                    <dt className="flex flex-wrap items-center gap-2 font-medium">
                      {d.term}
                      {d.timestamp !== null && <TimestampChip seconds={d.timestamp} lectureId={lectureId} />}
                    </dt>
                    <dd className="mt-0.5 text-muted-foreground">{d.definition}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">No definitions were found in this lecture.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
          <CardTitle>Topic notes</CardTitle>
          {data.topics.length > 1 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setOpen(allOpen ? new Set() : new Set(data.topics.map((_, i) => i)))}
            >
              {allOpen ? "Collapse all" : "Expand all"}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-2">
          {data.topics.length ? (
            data.topics.map((t, i) => (
              <TopicItem key={i} index={i} topic={t} lectureId={lectureId} open={open.has(i)} onToggle={() => toggle(i)} />
            ))
          ) : (
            <p className="text-sm text-muted-foreground">No topics were identified.</p>
          )}
        </CardContent>
      </Card>

      {data.revision_notes_md.trim() && (
        <Card>
          <CardHeader>
            <CardTitle>Revision notes</CardTitle>
          </CardHeader>
          <CardContent>
            <Markdown>{data.revision_notes_md}</Markdown>
          </CardContent>
        </Card>
      )}

      <p className="text-xs text-muted-foreground">
        Generated {formatDateTime(m.generated_at)}
        {m.provider ? ` · ${m.provider}` : ""}
        {m.model ? ` · ${m.model}` : ""}
        {m.prompt_version ? ` · ${m.prompt_version}` : ""}
        {m.mode ? ` · ${m.mode.replace("_", " ")}` : ""}
        {data.cached ? " · from cache" : ""}
      </p>
    </div>
  );
}

function TopicItem({
  index,
  topic,
  lectureId,
  open,
  onToggle,
}: {
  index: number;
  topic: TopicOut;
  lectureId: string;
  open: boolean;
  onToggle: () => void;
}) {
  const panelId = `topic-panel-${index}`;
  return (
    <div className="rounded-xl border">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 text-left text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ChevronDown className={cn("size-4 shrink-0 transition-transform", open && "rotate-180")} />
          <span className="min-w-0">{topic.title}</span>
        </button>
        <TimestampChip seconds={topic.start} end={topic.end} lectureId={lectureId} className="shrink-0" />
      </div>
      {open && (
        <div id={panelId} className="space-y-3 border-t px-4 py-3">
          <Markdown>{topic.notes_md}</Markdown>
          {topic.key_points.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Key points</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                {topic.key_points.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NotesSkeleton() {
  return (
    <div className="space-y-4" aria-label="Loading notes">
      <Skeleton className="h-36 w-full rounded-2xl" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-48 rounded-2xl" />
        <Skeleton className="h-48 rounded-2xl" />
      </div>
      <Skeleton className="h-64 w-full rounded-2xl" />
    </div>
  );
}
