/**
 * Toasts built from the backend error envelope. The backend's `message` is already written for
 * people; a few codes get a friendlier title or a hint about what to do next.
 */
import { toast } from "sonner";

import { ApiError, isApiError } from "@/api/client";

const TITLES: Record<string, string> = {
  NETWORK_ERROR: "Server unreachable",
  BACKEND_UNREACHABLE: "Backend not running",
  RATE_LIMITED: "Free-tier rate limit reached",
  MODEL_UNAVAILABLE: "Model not available",
  PROVIDER_NOT_CONFIGURED: "AI provider not configured",
  GENERATION_IN_PROGRESS: "Already generating",
  LECTURE_NOT_READY: "Lecture not ready yet",
  NOTES_NOT_GENERATED: "Notes not generated yet",
  FILE_TOO_LARGE: "File too large",
  UNSUPPORTED_MEDIA_TYPE: "Unsupported file",
  FFMPEG_NOT_FOUND: "ffmpeg missing on the server",
  LLM_OUTPUT_INVALID: "The model returned an invalid answer",
  VALIDATION_ERROR: "Please check your input",
  INTERNAL_ERROR: "Something went wrong",
};

/** A one-line description for an error, used in toasts and inline error states. */
export function describeError(err: unknown): { title: string; description: string } {
  if (isApiError(err)) {
    let description = err.message;
    if (err.code === "RATE_LIMITED") {
      description = err.retryAfter
        ? `Groq's free tier asked us to wait ${Math.ceil(err.retryAfter)} s. Try again then.`
        : "Groq's free tier is busy. Wait a minute and try again.";
    } else if (err.code === "VALIDATION_ERROR") {
      const errors = (err.details.errors as { loc?: unknown[]; msg?: string }[] | undefined) ?? [];
      if (errors.length) {
        description = errors
          .map((e) => `${(e.loc ?? []).filter((p) => p !== "body").join(".") || "input"}: ${e.msg ?? ""}`)
          .join("; ");
      }
    }
    return { title: TITLES[err.code] ?? (err.status >= 500 ? "Server error" : "Request failed"), description };
  }
  return { title: "Something went wrong", description: err instanceof Error ? err.message : String(err) };
}

export function notifyError(err: unknown, title?: string): void {
  if (err instanceof ApiError && err.code === "CANCELLED") return;
  const d = describeError(err);
  toast.error(title ?? d.title, { description: d.description });
}

export function notifySuccess(title: string, description?: string): void {
  toast.success(title, { description });
}
