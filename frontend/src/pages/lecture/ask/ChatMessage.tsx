import { Bot, Clock, Info, SearchX } from "lucide-react";
import { Link } from "react-router-dom";

import type { AskMeta, ChatMessageOut, SourceOut } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { refusalText, splitCitations } from "@/lib/chat";
import { formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A source chip: lecture time range + similarity; links to the transcript at that time. */
function SourceChip({ source, lectureId }: { source: SourceOut; lectureId: string }) {
  return (
    <Link
      to={`/lectures/${lectureId}/transcript?t=${Math.floor(source.start)}`}
      title={source.excerpt}
      aria-label={`${source.cited ? "Source" : "Closest part"} ${source.chunk_id}: ${formatTimestamp(source.start)} to ${formatTimestamp(source.end)}, similarity ${source.score.toFixed(2)}. Open in transcript`}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        source.cited
          ? "border-primary/30 bg-accent text-accent-foreground hover:bg-primary hover:text-primary-foreground"
          : "border-dashed text-muted-foreground hover:bg-muted",
      )}
    >
      <span className="font-semibold">{source.chunk_id}</span>
      <Clock className="size-3" />
      <span className="font-mono tabular-nums">
        {formatTimestamp(source.start)}–{formatTimestamp(source.end)}
      </span>
      <span className="tabular-nums opacity-70">{source.score.toFixed(2)}</span>
    </Link>
  );
}

export function ChatMessage({
  message,
  lectureId,
  meta,
}: {
  message: ChatMessageOut;
  lectureId: string;
  /** Only for answers received in this browser session (history doesn't keep meta). */
  meta?: AskMeta & { rewritten_question?: string | null };
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm text-primary-foreground">
          {message.content}
        </p>
      </div>
    );
  }

  const refused = message.answerable === false;
  return (
    <div className="flex gap-2.5">
      <div className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground">
        <Bot className="size-4" />
      </div>
      <div className="min-w-0 max-w-[85%] space-y-2">
        <div className={cn("rounded-2xl rounded-tl-md border bg-card px-4 py-2.5 text-sm shadow-sm", refused && "border-warning/40")}>
          {refused && (
            <div className="mb-2 space-y-1">
              <Badge variant="warning">
                <SearchX /> Not in lecture
              </Badge>
              <p className="text-xs text-muted-foreground">{refusalText(message.refusal_reason)}</p>
            </div>
          )}
          <p className="whitespace-pre-wrap leading-relaxed">
            {splitCitations(message.content).map((part, i) =>
              part.citation ? (
                <sup key={i} className="mx-0.5 font-semibold text-primary">
                  {part.text}
                </sup>
              ) : (
                <span key={i}>{part.text}</span>
              ),
            )}
          </p>
        </div>
        {message.sources.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">
              {refused ? "Closest parts of the lecture" : "Sources"}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {message.sources.map((s) => (
                <SourceChip key={s.chunk_id} source={s} lectureId={lectureId} />
              ))}
            </div>
          </div>
        )}
        {(meta || message.model) && (
          <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
            <Info className="size-3" />
            {meta ? <span>{meta.generator}</span> : message.model ? <span>{message.model}</span> : null}
            {meta && <span>· {(meta.latency_ms / 1000).toFixed(1)} s</span>}
            {meta?.rewritten_question && <span>· searched for “{meta.rewritten_question}”</span>}
          </p>
        )}
      </div>
    </div>
  );
}
