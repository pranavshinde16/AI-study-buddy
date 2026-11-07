import { useEffect, useState } from "react";

/**
 * true once `active` has stayed true for `afterMs`. Used to show "Waiting for the free-tier
 * rate limit…" so a long Groq pause doesn't look like a frozen app.
 */
export function useSlowFlag(active: boolean, afterMs = 8000): boolean {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!active) return;
    const t = setTimeout(() => setSlow(true), afterMs);
    return () => {
      clearTimeout(t);
      setSlow(false);
    };
  }, [active, afterMs]);
  return active && slow;
}
