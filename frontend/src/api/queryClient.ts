/**
 * TanStack Query setup. Queries show their errors inline; mutations toast their errors
 * automatically (set `meta: { silentError: true }` to handle an error yourself).
 */
import { MutationCache, QueryClient } from "@tanstack/react-query";

import { notifyError } from "@/lib/notify";
import { ApiError } from "./client";

declare module "@tanstack/react-query" {
  interface Register {
    defaultError: ApiError;
    mutationMeta: { silentError?: boolean };
  }
}

function shouldRetry(failureCount: number, error: unknown): boolean {
  // 4xx are answers, not glitches (404, 409 not ready, 422...). Retry network/5xx once.
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: false, staleTime: 30_000 },
      mutations: { retry: false },
    },
    mutationCache: new MutationCache({
      onError: (error, _vars, _ctx, mutation) => {
        if (error instanceof ApiError && error.status === 401 && !mutation.options.meta?.silentError) return;
        if (!mutation.options.meta?.silentError) notifyError(error);
      },
    }),
  });
}
