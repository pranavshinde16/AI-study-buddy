/**
 * TanStack Query hooks: caching, loading/error state and refetching for every endpoint.
 * Query keys live in `keys` so mutations can update or invalidate the right cache entries.
 */
import { useSyncExternalStore } from "react";
import { useMutation, useQueries, useQuery, useQueryClient, type Query } from "@tanstack/react-query";

import { getToken, setToken, clearToken, subscribeToken } from "./auth";
import { resetUnauthorizedGuard, type ApiError } from "./client";
import * as ep from "./endpoints";
import type {
  ChatRequest,
  GenerateQuizRequest,
  LectureOut,
  LectureStatus,
  LectureStatusOut,
  LlmOpsFilters,
  LoginRequest,
  RegisterRequest,
  SubmitQuizRequest,
} from "./types";

export const keys = {
  me: ["me"] as const,
  lectures: ["lectures"] as const,
  lecture: (id: string) => ["lecture", id] as const,
  status: (id: string) => ["lecture", id, "status"] as const,
  transcript: (id: string) => ["lecture", id, "transcript"] as const,
  summary: (id: string) => ["lecture", id, "summary"] as const,
  notes: (id: string) => ["lecture", id, "notes"] as const,
  quizzes: (id: string) => ["lecture", id, "quizzes"] as const,
  quiz: (quizId: string) => ["quiz", quizId] as const,
  deck: (id: string, dueOnly: boolean) => ["lecture", id, "deck", dueOnly ? "due" : "all"] as const,
  deckAll: (id: string) => ["lecture", id, "deck"] as const,
  chatSessions: (id: string) => ["lecture", id, "chat"] as const,
  chatHistory: (id: string, sessionId: string) => ["lecture", id, "chat", sessionId] as const,
  models: ["models"] as const,
  llmops: (part: string, f?: LlmOpsFilters, extra?: string) => ["llmops", part, f ?? {}, extra ?? ""] as const,
};

/** Statuses where the pipeline is still moving, so /status is worth polling. */
export const ACTIVE_STATUSES: ReadonlySet<LectureStatus> = new Set([
  "uploaded",
  "extracting_audio",
  "transcribing",
  "indexing",
  "generating",
]);

/** Statuses where GET /transcript works (backend TRANSCRIPT_READY). */
export const TRANSCRIPT_STATUSES: ReadonlySet<LectureStatus> = new Set([
  "indexing",
  "transcribed",
  "generating",
  "ready",
]);

export const STATUS_POLL_MS = 3000;

// ------------------------------------------------------------------ auth
export function useAuthToken(): string | null {
  return useSyncExternalStore(subscribeToken, getToken, getToken);
}

export function useMe() {
  const token = useAuthToken();
  return useQuery({ queryKey: keys.me, queryFn: ep.getMe, enabled: !!token, staleTime: 5 * 60_000 });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: LoginRequest) => ep.login(body),
    meta: { silentError: true },
    onSuccess: (tok) => {
      qc.clear();
      setToken(tok.access_token, tok.expires_in);
      resetUnauthorizedGuard();
    },
  });
}

export function useRegister() {
  return useMutation({ mutationFn: (body: RegisterRequest) => ep.register(body), meta: { silentError: true } });
}

export function useLogout() {
  const qc = useQueryClient();
  return () => {
    clearToken();
    qc.clear();
  };
}

// ------------------------------------------------------------------ lectures
export function useLectures() {
  return useQuery({ queryKey: keys.lectures, queryFn: ep.listLectures });
}

export function useLecture(id: string) {
  return useQuery({ queryKey: keys.lecture(id), queryFn: () => ep.getLecture(id) });
}

/**
 * Polls /status every 3 s while the pipeline is running (or while `keepPolling` is true,
 * e.g. during a summary retry). Stops on ready/failed or a summary error.
 */
export function useLectureStatus(id: string, keepPolling = false) {
  return useQuery({
    queryKey: keys.status(id),
    queryFn: () => ep.getLectureStatus(id),
    staleTime: 0,
    refetchInterval: (query: Query<LectureStatusOut, ApiError>) => {
      if (keepPolling) return STATUS_POLL_MS;
      const data = query.state.data;
      if (query.state.status === "error") return false;
      if (!data) return STATUS_POLL_MS;
      if (ACTIVE_STATUSES.has(data.status)) return STATUS_POLL_MS;
      // transcribed without an error: the automatic summary may be about to start.
      if (data.status === "transcribed" && !data.error) return STATUS_POLL_MS;
      return false;
    },
  });
}

export function useDeleteLecture() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => ep.deleteLecture(id),
    onSuccess: (_d, id) => {
      qc.removeQueries({ queryKey: keys.lecture(id) });
      void qc.invalidateQueries({ queryKey: keys.lectures });
    },
  });
}

// ------------------------------------------------------------------ transcript
export function useTranscript(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.transcript(id),
    queryFn: () => ep.getTranscript(id),
    enabled,
    staleTime: Infinity,
  });
}

// ------------------------------------------------------------------ summary
/** Reads the stored summary. Only enable it when the lecture is `ready` (otherwise POST would generate). */
export function useSummary(id: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.summary(id),
    queryFn: () => ep.summarize(id, false),
    enabled,
    staleTime: Infinity,
  });
}

/** Generates (or regenerates) the summary and notes; slow on the free tier. */
export function useSummarize(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (regenerate: boolean) => ep.summarize(id, regenerate),
    onSuccess: (data) => {
      qc.setQueryData(keys.summary(id), data);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: keys.lecture(id), exact: true });
      void qc.invalidateQueries({ queryKey: keys.status(id) });
      void qc.invalidateQueries({ queryKey: keys.lectures });
    },
  });
}

/** Topic-wise notes (topic titles feed the quiz setup). 409 NOTES_NOT_GENERATED until /summarize ran. */
export function useNotes(id: string, enabled = true) {
  return useQuery({ queryKey: keys.notes(id), queryFn: () => ep.getNotes(id), enabled, staleTime: 5 * 60_000 });
}

// ------------------------------------------------------------------ quizzes
export function useQuizzes(id: string) {
  return useQuery({ queryKey: keys.quizzes(id), queryFn: () => ep.listQuizzes(id) });
}

export function useGenerateQuiz(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GenerateQuizRequest) => ep.generateQuiz(id, body),
    onSuccess: (quiz) => {
      qc.setQueryData(keys.quiz(quiz.quiz_id), quiz);
      void qc.invalidateQueries({ queryKey: keys.quizzes(id) });
    },
  });
}

/** Loads an earlier quiz (without answers) to take it again. */
export function useLoadQuiz() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (quizId: string) => qc.fetchQuery({ queryKey: keys.quiz(quizId), queryFn: () => ep.getQuiz(quizId) }),
  });
}

export function useSubmitQuiz(lectureId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ quizId, body }: { quizId: string; body: SubmitQuizRequest }) => ep.submitQuiz(quizId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.quizzes(lectureId) });
    },
  });
}

// ------------------------------------------------------------------ flashcards
export function useDeck(id: string, dueOnly: boolean, enabled = true) {
  return useQuery({ queryKey: keys.deck(id, dueOnly), queryFn: () => ep.getDeck(id, dueOnly), enabled });
}

export function useGenerateDeck(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (regenerate: boolean) => ep.generateDeck(id, regenerate),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.deckAll(id) });
    },
  });
}

export function useReviewCard(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ cardId, knew }: { cardId: string; knew: boolean }) => ep.reviewCard(cardId, knew),
    // Mark decks stale without refetching: the review session keeps its own queue until it ends.
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.deckAll(id), refetchType: "none" });
    },
  });
}

// ------------------------------------------------------------------ ask / chat
export function useModels() {
  return useQuery({ queryKey: keys.models, queryFn: ep.listModels, staleTime: 10 * 60_000 });
}

export function useChatSessions(id: string) {
  return useQuery({ queryKey: keys.chatSessions(id), queryFn: () => ep.listChatSessions(id) });
}

export function useChatHistory(id: string, sessionId: string | null) {
  return useQuery({
    queryKey: keys.chatHistory(id, sessionId ?? ""),
    queryFn: () => ep.getChatHistory(id, sessionId!),
    enabled: !!sessionId,
    staleTime: Infinity,
  });
}

export function useSendChat(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ChatRequest) => ep.sendChat(id, body),
    // The Ask page shows MODEL_UNAVAILABLE and rate limits inline, with its own wording.
    meta: { silentError: true },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.chatSessions(id), exact: true });
    },
  });
}

// ------------------------------------------------------------------ LLMOps (Phase 11)
/** Every metric the LLMOps page shows, for one set of filters. Logs change slowly; 30 s is enough. */
export function useLlmOps(f: LlmOpsFilters) {
  const opts = { staleTime: 30_000 };
  return {
    summary: useQuery({ queryKey: keys.llmops("summary", f), queryFn: () => ep.getLlmOpsSummary(f), ...opts }),
    latency: useQuery({ queryKey: keys.llmops("latency", f), queryFn: () => ep.getTaskLatency(f), ...opts }),
    qaLatency: useQuery({ queryKey: keys.llmops("qa-latency", f), queryFn: () => ep.getQALatency(f), ...opts }),
    usageTask: useQuery({ queryKey: keys.llmops("usage", f, "task"), queryFn: () => ep.getUsage(f, "task"), ...opts }),
    usageDay: useQuery({ queryKey: keys.llmops("usage", f, "day"), queryFn: () => ep.getUsage(f, "day"), ...opts }),
    usageLecture: useQuery({
      queryKey: keys.llmops("usage", f, "lecture"),
      queryFn: () => ep.getUsage(f, "lecture"),
      ...opts,
    }),
    transcription: useQuery({
      queryKey: keys.llmops("transcription", f),
      queryFn: () => ep.getTranscriptionMetrics(f),
      ...opts,
    }),
    errors: useQuery({ queryKey: keys.llmops("errors", f), queryFn: () => ep.getErrors(f), ...opts }),
    refusals: useQuery({ queryKey: keys.llmops("refusals", f), queryFn: () => ep.getRefusals(f), ...opts }),
    prompts: useQuery({ queryKey: keys.llmops("prompts", f), queryFn: () => ep.getPromptMetrics(f), ...opts }),
  };
}

export function useLlmOpsFilterOptions() {
  return useQuery({ queryKey: keys.llmops("filters"), queryFn: ep.getLlmOpsFilters, staleTime: 60_000 });
}

export function useModelRegistry() {
  return useQuery({ queryKey: keys.llmops("models"), queryFn: ep.getModelRegistry, staleTime: 60_000 });
}

export function useEvalRuns() {
  return useQuery({ queryKey: keys.llmops("eval-runs"), queryFn: ep.listEvalRuns, staleTime: 30_000 });
}

export function useEvalCompare(goldenSet: string | null) {
  return useQuery({
    queryKey: keys.llmops("eval-compare", undefined, goldenSet ?? ""),
    queryFn: () => ep.getEvalCompare(goldenSet),
    staleTime: 30_000,
  });
}

// ------------------------------------------------------------------ dashboard / analytics
/**
 * Quiz lists and decks for every lecture, built from existing endpoints only
 * (Phase 9 adds /progress and /dashboard/overview). `allCards` = full decks instead of due cards.
 */
export function useLectureStats(lectures: LectureOut[] | undefined, allCards = false) {
  const list = lectures ?? [];
  const quizzes = useQueries({
    queries: list.map((l) => ({ queryKey: keys.quizzes(l.id), queryFn: () => ep.listQuizzes(l.id) })),
  });
  const decks = useQueries({
    queries: list.map((l) => ({ queryKey: keys.deck(l.id, !allCards), queryFn: () => ep.getDeck(l.id, !allCards) })),
  });
  return {
    quizzes,
    decks,
    isPending: quizzes.some((q) => q.isPending) || decks.some((d) => d.isPending),
    isError: quizzes.some((q) => q.isError) || decks.some((d) => d.isError),
  };
}
