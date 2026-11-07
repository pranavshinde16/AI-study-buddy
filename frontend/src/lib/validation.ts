/** Client-side checks that mirror backend/app/schemas/auth.py (the backend still validates). */

export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;
export const PASSWORD_MAX_BYTES = 72; // bcrypt limit

export function validateEmail(email: string): string | null {
  const v = email.trim();
  if (!v) return "Enter your email address";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return "Enter a valid email address";
  return null;
}

export function validateNewPassword(password: string): string | null {
  if (password.length < PASSWORD_MIN) return `Use at least ${PASSWORD_MIN} characters`;
  if (password.length > PASSWORD_MAX) return `Use at most ${PASSWORD_MAX} characters`;
  if (new TextEncoder().encode(password).length > PASSWORD_MAX_BYTES) {
    return `Too long: at most ${PASSWORD_MAX_BYTES} bytes (accented letters and emoji count as several)`;
  }
  return null;
}
