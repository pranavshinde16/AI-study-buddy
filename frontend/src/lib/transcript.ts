import type { SegmentOut } from "@/api/types";

/** Index (segment id) of the segment playing at `seconds`, or the last one that started before it. */
export function segmentAt(segments: SegmentOut[], seconds: number): number | null {
  let found: number | null = null;
  for (const s of segments) {
    if (s.start <= seconds) found = s.id;
    else break;
  }
  return found;
}

/** Splits text into matching / non-matching parts for <mark> highlighting (case-insensitive). */
export function splitForHighlight(text: string, query: string): { text: string; match: boolean }[] {
  const q = query.trim();
  if (!q) return [{ text, match: false }];
  const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text
    .split(new RegExp(`(${escaped})`, "gi"))
    .filter((p) => p !== "")
    .map((p) => ({ text: p, match: p.toLowerCase() === q.toLowerCase() }));
}
