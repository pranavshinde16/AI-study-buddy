import type { ApiError } from "@/api/client";
import type { ChatHistoryOut, ChatMessageOut, ChatResponse, RefusalReason } from "@/api/types";
import { describeError } from "./notify";

export const REFUSAL_TEXT: Record<RefusalReason, string> = {
  below_threshold: "No part of the lecture was similar enough to the question, so the model wasn't asked.",
  not_in_chunks: "The closest parts of the lecture don't contain the answer.",
};

export function refusalText(reason: string | null | undefined): string {
  if (reason && reason in REFUSAL_TEXT) return REFUSAL_TEXT[reason as RefusalReason];
  return "The lecture doesn't cover this question.";
}

/** Splits "… [C1] … [C2]." into text and citation parts so citations can be styled. */
export function splitCitations(text: string): { text: string; citation: boolean }[] {
  return text
    .split(/(\[C\d+\])/g)
    .filter((p) => p !== "")
    .map((p) => ({ text: p, citation: /^\[C\d+\]$/.test(p) }));
}

/** Adds a live /chat answer (user + assistant message) to the cached history of its session. */
export function appendTurn(
  prev: ChatHistoryOut | undefined,
  lectureId: string,
  res: ChatResponse,
  model: string,
  now = new Date().toISOString(),
): ChatHistoryOut {
  const user: ChatMessageOut = {
    id: `${res.message_id}-q`,
    role: "user",
    content: res.question,
    sources: [],
    answerable: null,
    refusal_reason: null,
    model: null,
    created_at: now,
  };
  const reply: ChatMessageOut = {
    id: res.message_id,
    role: "assistant",
    content: res.answer,
    sources: res.sources,
    answerable: res.answerable,
    refusal_reason: res.meta.refusal_reason,
    model,
    created_at: now,
  };
  return {
    session_id: res.session_id,
    lecture_id: lectureId,
    title: prev?.title ?? res.question,
    created_at: prev?.created_at ?? now,
    messages: [...(prev?.messages ?? []), user, reply],
  };
}

/** The message shown for a failed chat request; MODEL_UNAVAILABLE gets its own wording. */
export function chatErrorText(err: ApiError, model: string): { title: string; description: string } {
  if (err.code === "MODEL_UNAVAILABLE") {
    return {
      title: model === "cloud" ? "Model not available" : "Fine-tuned model not available yet",
      description:
        model === "cloud"
          ? err.message
          : `The "${model}" model runs locally through Ollama, which isn't running or doesn't have the model yet (the fine-tuned model arrives in Phase 10). Switch to "cloud" to keep asking. Details: ${err.message}`,
    };
  }
  return describeError(err);
}
