/**
 * The one axios instance every request goes through.
 * - Adds `Authorization: Bearer <token>`.
 * - Turns every failure into an ApiError built from the backend envelope {"error": {code, message, details}}.
 * - On a 401 for a logged-in request: clears the token and calls the unauthorized handler
 *   (main.tsx sends you to /login?next=<page>).
 */
import axios, { AxiosError, AxiosHeaders, type AxiosRequestConfig } from "axios";

import { clearToken, getToken } from "./auth";
import type { ErrorEnvelope } from "./types";

declare module "axios" {
  interface AxiosRequestConfig {
    /** Don't treat a 401 as "session expired" (login uses this: 401 means wrong password there). */
    skipAuthRedirect?: boolean;
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  /** Seconds from the Retry-After header (429), when the backend sent one. */
  readonly retryAfter: number | null;

  constructor(opts: {
    status: number;
    code: string;
    message: string;
    details?: Record<string, unknown>;
    retryAfter?: number | null;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code;
    this.details = opts.details ?? {};
    this.retryAfter = opts.retryAfter ?? null;
  }
}

export function isApiError(err: unknown, code?: string): err is ApiError {
  return err instanceof ApiError && (code === undefined || err.code === code);
}

function isEnvelope(data: unknown): data is ErrorEnvelope {
  if (!data || typeof data !== "object" || !("error" in data)) return false;
  const e = (data as { error: unknown }).error;
  return !!e && typeof e === "object" && typeof (e as { code?: unknown }).code === "string";
}

/** Blob/arraybuffer requests (downloads, media) get their error body as a Blob; read it as JSON. */
async function readBody(data: unknown): Promise<unknown> {
  if (typeof Blob !== "undefined" && data instanceof Blob) {
    try {
      return JSON.parse(await data.text());
    } catch {
      return null;
    }
  }
  return data;
}

export async function toApiError(err: unknown): Promise<ApiError> {
  if (err instanceof ApiError) return err;
  if (axios.isCancel(err)) {
    return new ApiError({ status: 0, code: "CANCELLED", message: "The request was cancelled" });
  }
  if (err instanceof AxiosError) {
    if (!err.response) {
      return new ApiError({
        status: 0,
        code: "NETWORK_ERROR",
        message: "Can't reach the server. Check that the backend is running.",
      });
    }
    const { status, headers } = err.response;
    const body = await readBody(err.response.data);
    const retryRaw = headers?.["retry-after"];
    const retryAfter = retryRaw !== undefined && !Number.isNaN(Number(retryRaw)) ? Number(retryRaw) : null;
    if (isEnvelope(body)) {
      return new ApiError({ status, ...body.error, retryAfter });
    }
    // The backend always answers with an envelope, so a bare 502/503/504 comes from the dev proxy
    // (or another gateway) failing to reach it, usually because uvicorn isn't running.
    if (status === 502 || status === 503 || status === 504) {
      return new ApiError({
        status,
        code: "BACKEND_UNREACHABLE",
        message: "Can't reach the backend. Check that it is running (uvicorn) on the port the frontend proxies to.",
      });
    }
    return new ApiError({ status, code: "HTTP_ERROR", message: `Request failed (HTTP ${status})`, retryAfter });
  }
  return new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: err instanceof Error ? err.message : String(err) });
}

// ------------------------------------------------------------------ 401 handling

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler = () => {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.assign(`/login?next=${next}&reason=expired`);
};
let redirecting = false;

/** main.tsx installs a router-aware handler; tests install a spy. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  unauthorizedHandler = handler;
  redirecting = false;
}

/** Called after a successful login so the next expiry redirects again. */
export function resetUnauthorizedGuard(): void {
  redirecting = false;
}

// ------------------------------------------------------------------ the instance

export const api = axios.create({ baseURL: "/api" });

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    const headers = AxiosHeaders.from(config.headers);
    headers.set("Authorization", `Bearer ${token}`);
    config.headers = headers;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (err: unknown) => {
    const apiError = await toApiError(err);
    const config = err instanceof AxiosError ? (err.config as AxiosRequestConfig | undefined) : undefined;
    if (apiError.status === 401 && !config?.skipAuthRedirect) {
      clearToken();
      if (!redirecting) {
        redirecting = true;
        unauthorizedHandler();
      }
    }
    throw apiError;
  },
);
