/**
 * JWT storage. The access token lives in localStorage with its expiry time, so a reload keeps
 * you logged in until the backend's ACCESS_TOKEN_EXPIRE_MINUTES runs out.
 */

const STORAGE_KEY = "studybuddy.auth";

interface StoredToken {
  token: string;
  /** Epoch milliseconds. */
  expiresAt: number;
}

type Listener = () => void;
const listeners = new Set<Listener>();

function read(): StoredToken | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredToken;
    if (typeof parsed.token !== "string" || typeof parsed.expiresAt !== "number") return null;
    return parsed;
  } catch {
    return null;
  }
}

/** The current token, or null if there is none or it has expired. */
export function getToken(): string | null {
  const stored = read();
  if (!stored) return null;
  if (Date.now() >= stored.expiresAt) {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
  return stored.token;
}

export function setToken(token: string, expiresInSec: number): void {
  const value: StoredToken = { token, expiresAt: Date.now() + expiresInSec * 1000 };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  listeners.forEach((l) => l());
}

export function clearToken(): void {
  localStorage.removeItem(STORAGE_KEY);
  listeners.forEach((l) => l());
}

/** Subscribe to login/logout (used by useSyncExternalStore in useAuthToken). */
export function subscribeToken(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
