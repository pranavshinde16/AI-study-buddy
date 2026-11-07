import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download, FileText, Hourglass, Loader2, Search, X } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { downloadTranscript } from "@/api/endpoints";
import { TRANSCRIPT_STATUSES, useLecture, useTranscript } from "@/api/hooks";
import type { SegmentOut, TranscriptFormat } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MediaPlayer, type MediaPlayerHandle } from "@/components/MediaPlayer";
import { TimestampChip } from "@/components/TimestampChip";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { saveBlob, safeFilename } from "@/lib/download";
import { formatDuration } from "@/lib/format";
import { notifySuccess } from "@/lib/notify";
import { segmentAt, splitForHighlight } from "@/lib/transcript";
import { cn } from "@/lib/utils";

const FORMATS: TranscriptFormat[] = ["txt", "srt", "vtt"];

export function TranscriptPage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const lecture = useLecture(id);
  const ready = !!lecture.data && TRANSCRIPT_STATUSES.has(lecture.data.status);
  const transcript = useTranscript(id, ready);

  const playerRef = useRef<MediaPlayerHandle>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  const startParam = params.get("t");
  const startAt = startParam !== null && !Number.isNaN(Number(startParam)) ? Math.max(0, Number(startParam)) : null;
  const segments = useMemo(() => transcript.data?.segments ?? [], [transcript.data]);
  const linkedIdx = startAt !== null ? segmentAt(segments, startAt) : null;
  const highlightIdx = activeIdx ?? linkedIdx;

  // Coming from a ?t= link (notes, quiz): scroll that segment into view once the transcript loads.
  useEffect(() => {
    if (linkedIdx === null) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-seg="${linkedIdx}"]`);
    el?.scrollIntoView?.({ block: "center" });
  }, [linkedIdx]);

  const download = useMutation({
    mutationFn: (format: TranscriptFormat) => downloadTranscript(id, format),
    onSuccess: (file, format) => {
      const name = file.filename ?? safeFilename(lecture.data?.title ?? "transcript", format);
      saveBlob(file.blob, name);
      notifySuccess("Download started", name);
    },
  });

  const q = query.trim().toLowerCase();
  const visible: SegmentOut[] = q ? segments.filter((s) => s.text.toLowerCase().includes(q)) : segments;

  if (lecture.isError) return <ErrorState error={lecture.error} onRetry={() => void lecture.refetch()} />;
  if (lecture.data && !ready) {
    const failed = lecture.data.status === "failed";
    return (
      <EmptyState
        icon={failed ? X : Hourglass}
        title={failed ? "Processing failed" : "The transcript isn't ready yet"}
        description={failed ? lecture.data.error : `Current stage: ${lecture.data.stage_detail ?? lecture.data.status}.`}
        action={
          <Button asChild variant="outline">
            <Link to={`/lectures/${id}/processing`}>View progress</Link>
          </Button>
        }
      />
    );
  }
  if (transcript.isError) return <ErrorState error={transcript.error} onRetry={() => void transcript.refetch()} />;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4 pt-6">
          <MediaPlayer
            ref={playerRef}
            lectureId={id}
            sizeBytes={lecture.data?.size_bytes}
            startAt={startAt}
            onTime={(t) => setActiveIdx(segmentAt(segments, t))}
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="search"
                aria-label="Search the transcript"
                placeholder="Search the transcript"
                className="pl-9"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="flex gap-2" role="group" aria-label="Download transcript">
              {FORMATS.map((f) => (
                <Button
                  key={f}
                  variant="outline"
                  size="sm"
                  className="flex-1 sm:flex-none"
                  disabled={download.isPending || !transcript.data}
                  onClick={() => download.mutate(f)}
                  aria-label={`Download as ${f.toUpperCase()}`}
                >
                  {download.isPending && download.variables === f ? <Loader2 className="animate-spin" /> : <Download />}
                  {f.toUpperCase()}
                </Button>
              ))}
            </div>
          </div>
          {transcript.data && (
            <p className="text-xs text-muted-foreground">
              {segments.length} segments · {formatDuration(transcript.data.duration_sec)}
              {transcript.data.language ? ` · ${transcript.data.language}` : ""}
              {q ? ` · ${visible.length} match${visible.length === 1 ? "" : "es"}` : ""}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          {!transcript.data ? (
            <div className="space-y-3" aria-label="Loading transcript">
              {Array.from({ length: 8 }, (_, i) => (
                <div key={i} className="flex gap-3">
                  <Skeleton className="h-5 w-14" />
                  <Skeleton className="h-5 flex-1" />
                </div>
              ))}
            </div>
          ) : segments.length === 0 ? (
            <EmptyState icon={FileText} title="No speech was recognised" description="The transcript has no segments." />
          ) : visible.length === 0 ? (
            <EmptyState
              icon={Search}
              title={`No segments match "${query.trim()}"`}
              action={
                <Button variant="outline" size="sm" onClick={() => setQuery("")}>
                  Clear search
                </Button>
              }
            />
          ) : (
            <ol ref={listRef} className="max-h-[65vh] space-y-1 overflow-y-auto pr-1" aria-label="Transcript segments">
              {visible.map((seg) => (
                <li
                  key={seg.id}
                  data-seg={seg.id}
                  aria-current={seg.id === highlightIdx ? "true" : undefined}
                  className={cn(
                    "flex gap-3 rounded-lg px-2 py-1.5 transition-colors",
                    seg.id === highlightIdx ? "bg-accent" : "hover:bg-muted/60",
                  )}
                >
                  <TimestampChip seconds={seg.start} onSeek={(s) => playerRef.current?.seek(s)} className="mt-0.5 h-fit shrink-0" />
                  <p className="text-sm leading-relaxed">
                    {splitForHighlight(seg.text, q).map((part, i) =>
                      part.match ? (
                        <mark key={i} className="rounded bg-warning/25 px-0.5 text-foreground">
                          {part.text}
                        </mark>
                      ) : (
                        <span key={i}>{part.text}</span>
                      ),
                    )}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
