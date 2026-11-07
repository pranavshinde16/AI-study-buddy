import type { ReactNode } from "react";
import { Hourglass } from "lucide-react";

/** Shown while a slow LLM request is pending, so a free-tier pause doesn't look frozen. */
export function SlowNotice({ show, children }: { show: boolean; children?: ReactNode }) {
  if (!show) return null;
  return (
    <div role="status" className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
      <Hourglass className="mt-0.5 size-4 shrink-0 animate-pulse" />
      <span>{children ?? "Waiting for the free-tier rate limit… this can take up to a minute."}</span>
    </div>
  );
}
