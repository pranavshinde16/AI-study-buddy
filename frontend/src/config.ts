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
};
