import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, Hourglass, Loader2, MessageSquarePlus, MessagesSquare, Send, X } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import {
  keys,
  TRANSCRIPT_STATUSES,
  useChatHistory,
  useChatSessions,
  useLecture,
  useModels,
  useSendChat,
} from "@/api/hooks";
import type { AskMeta, ChatHistoryOut, GeneratorOut } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SlowNotice } from "@/components/SlowNotice";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { config } from "@/config";
import { useSlowFlag } from "@/hooks/useSlowFlag";
import { appendTurn, chatErrorText } from "@/lib/chat";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ChatMessage } from "./ChatMessage";

export function AskPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const lecture = useLecture(id);
  const ready = !!lecture.data && TRANSCRIPT_STATUSES.has(lecture.data.status);
  const sessions = useChatSessions(id);
  const models = useModels();
  const send = useSendChat(id);
  const slow = useSlowFlag(send.isPending, config.slowRequestMs);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [liveMeta, setLiveMeta] = useState<Record<string, AskMeta & { rewritten_question: string | null }>>({});
  const history = useChatHistory(id, sessionId);
  const bottomRef = useRef<HTMLDivElement>(null);

  const modelList: GeneratorOut[] = models.data ?? [];
  const selectedModel = model ?? (modelList.find((m) => m.name === "cloud")?.name || modelList[0]?.name || "cloud");
  const messages = history.data?.messages ?? [];

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, pendingQuestion]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const question = draft.trim();
    if (!question || send.isPending || question.length > config.maxQuestionChars) return;
    setPendingQuestion(question);
    setDraft("");
    send.mutate(
      { message: question, session_id: sessionId, model: selectedModel },
      {
        onSuccess: (res) => {
          qc.setQueryData<ChatHistoryOut>(keys.chatHistory(id, res.session_id), (prev) =>
            appendTurn(prev, id, res, selectedModel),
          );
          setLiveMeta((m) => ({ ...m, [res.message_id]: { ...res.meta, rewritten_question: res.rewritten_question } }));
          setSessionId(res.session_id);
        },
        onError: () => setDraft(question), // keep the question so it can be sent again
        onSettled: () => setPendingQuestion(null),
      },
    );
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  function newChat() {
    setSessionId(null);
    send.reset();
  }

  if (lecture.isError) return <ErrorState error={lecture.error} onRetry={() => void lecture.refetch()} />;
  if (lecture.data && !ready) {
    return (
      <EmptyState
        icon={Hourglass}
        title="Questions open once the transcript is ready"
        description="Answers come only from the transcript, so it has to exist first."
        action={
          <Button asChild variant="outline">
            <Link to={`/lectures/${id}/processing`}>View progress</Link>
          </Button>
        }
      />
    );
  }

  const tooLong = draft.length > config.maxQuestionChars;
  const err = send.error;
  const errText = err ? chatErrorText(err, selectedModel) : null;
  const current = modelList.find((m) => m.name === selectedModel);

  return (
    <div className="grid gap-4 md:grid-cols-[15rem_1fr]">
      <aside className="space-y-2" aria-label="Chat sessions">
        <Button variant="outline" className="w-full" onClick={newChat} disabled={send.isPending}>
          <MessageSquarePlus /> New chat
        </Button>
        {sessions.isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : sessions.data?.length ? (
          <ul className="flex gap-2 overflow-x-auto pb-1 md:block md:space-y-1 md:overflow-visible md:pb-0">
            {sessions.data.map((s) => (
              <li key={s.session_id} className="shrink-0 md:shrink">
                <button
                  type="button"
                  onClick={() => {
                    setSessionId(s.session_id);
                    send.reset();
                  }}
                  disabled={send.isPending}
                  aria-current={s.session_id === sessionId ? "true" : undefined}
                  className={cn(
                    "w-48 rounded-xl border px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:w-full",
                    s.session_id === sessionId ? "border-primary bg-accent" : "bg-card hover:bg-muted",
                  )}
                >
                  <p className="truncate font-medium">{s.title ?? "Untitled chat"}</p>
                  <p className="text-xs text-muted-foreground">
                    {s.messages} messages · {formatDateTime(s.created_at)}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-1 text-xs text-muted-foreground">No chats yet.</p>
        )}
      </aside>

      <Card className="flex min-h-[60vh] flex-col overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
          <MessagesSquare className="size-4 text-primary" />
          <p className="mr-auto text-sm font-medium">Answers come only from this lecture</p>
          <Label htmlFor="model" className="text-xs text-muted-foreground">
            Model
          </Label>
          <select
            id="model"
            value={selectedModel}
            onChange={(e) => {
              setModel(e.target.value);
              send.reset();
            }}
            disabled={models.isPending || send.isPending}
            title={current ? `${current.provider} · ${current.model}: ${current.description}` : undefined}
            className="h-8 rounded-lg border border-input bg-card px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {modelList.length === 0 && <option value="cloud">cloud</option>}
            {modelList.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name} ({m.provider})
              </option>
            ))}
          </select>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
          {sessionId && history.isPending ? (
            <div className="space-y-3">
              <Skeleton className="ml-auto h-10 w-2/3" />
              <Skeleton className="h-24 w-3/4" />
            </div>
          ) : sessionId && history.isError ? (
            <ErrorState error={history.error} onRetry={() => void history.refetch()} />
          ) : messages.length === 0 && !pendingQuestion ? (
            <EmptyState
              icon={Bot}
              title="Ask about this lecture"
              description="Answers cite the parts of the lecture they come from. If the lecture doesn't cover a question, you'll see why and where the closest parts are."
              className="border-0"
            />
          ) : (
            messages.map((m) => <ChatMessage key={m.id} message={m} lectureId={id} meta={liveMeta[m.id]} />)
          )}
          {pendingQuestion && (
            <>
              <div className="flex justify-end">
                <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary/80 px-4 py-2.5 text-sm text-primary-foreground">
                  {pendingQuestion}
                </p>
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
                <Loader2 className="size-4 animate-spin" /> Searching the lecture…
              </div>
            </>
          )}
          <SlowNotice show={slow} />
          <div ref={bottomRef} />
        </div>

        {errText && (
          <div role="alert" className="mx-4 mb-2 flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
            <div className="min-w-0 flex-1">
              <p className="font-medium">{errText.title}</p>
              <p className="text-muted-foreground">{errText.description}</p>
              {err?.code === "MODEL_UNAVAILABLE" && selectedModel !== "cloud" && (
                <Button size="sm" variant="outline" className="mt-2" onClick={() => { setModel("cloud"); send.reset(); }}>
                  Switch to cloud
                </Button>
              )}
            </div>
            <button type="button" aria-label="Dismiss" onClick={() => send.reset()} className="rounded p-1 hover:bg-muted">
              <X className="size-4" />
            </button>
          </div>
        )}

        <form onSubmit={submit} className="flex items-end gap-2 border-t p-3">
          <div className="flex-1">
            <textarea
              aria-label="Your question"
              rows={2}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Ask a question… (Enter to send, Shift+Enter for a new line)"
              disabled={send.isPending}
              aria-invalid={tooLong || undefined}
              className="w-full resize-none rounded-xl border border-input bg-card px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-invalid:border-destructive"
            />
            {tooLong && (
              <p className="text-xs text-destructive">
                {draft.length}/{config.maxQuestionChars} characters: shorten your question.
              </p>
            )}
          </div>
          <Button type="submit" size="icon" aria-label="Send" disabled={!draft.trim() || tooLong || send.isPending}>
            {send.isPending ? <Loader2 className="animate-spin" /> : <Send />}
          </Button>
        </form>
      </Card>
    </div>
  );
}
