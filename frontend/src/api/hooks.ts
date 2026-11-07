/**
 * TanStack Query hooks: caching, loading/error state and refetching for every endpoint.
 * Query keys live in `keys` so mutations can update or invalidate the right cache entries.
 */
import { useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient, type Query } from "@tanstack/react-query";

import { getToken, setToken, clearToken, subscribeToken } from "./auth";
import { resetUnauthorizedGuard, type ApiError } from "./client";
import * as ep from "./endpoints";
import type { LectureStatus, LectureStatusOut, LoginRequest, RegisterRequest } from "./types";

export const keys = {
  me: ["me"] as const,
  lectures: ["lectures"] as const,
  lecture: (id: string) => ["lecture", id] as const,
  status: (id: string) => ["lecture", id, "status"] as const,
  transcript: (id: string) => ["lecture", id, "transcript"] as const,
  summary: (id: string) => ["lecture", id, "summary"] as const,
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
