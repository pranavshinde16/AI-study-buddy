/**
 * Frontend settings from Vite env variables (frontend/.env, see frontend/.env.example).
 * Only VITE_* variables reach the browser; never put secrets here.
 */

function intFromEnv(raw: string | undefined, fallback: number): number {
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : fallback;
}

export const config = {
  /** Should match the backend's MAX_UPLOAD_MB; the backend's 413 is the real limit. */
  maxUploadMb: intFromEnv(import.meta.env.VITE_MAX_UPLOAD_MB, 500),
  /** File types the backend accepts (services/lectures.py ALLOWED_TYPES). */
  allowedExtensions: ["mp3", "wav", "mp4", "m4a"] as const,
  /** Should match the backend's QUIZ_MAX_QUESTIONS; the backend's 422 is the real limit. */
  quizMaxQuestions: intFromEnv(import.meta.env.VITE_QUIZ_MAX_QUESTIONS, 20),
  /** Should match the backend's RAG_MAX_QUESTION_CHARS. */
  maxQuestionChars: intFromEnv(import.meta.env.VITE_RAG_MAX_QUESTION_CHARS, 1000),
  /** After this long, slow LLM requests show "Waiting for the free-tier rate limit…". */
  slowRequestMs: 8000,
  features: {
    /** The backend returns 422 ADAPTIVE_NOT_AVAILABLE until Phase 9, so the toggle stays hidden. */
    adaptiveQuiz: false,
  },
};
