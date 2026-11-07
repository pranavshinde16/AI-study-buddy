import type { SummaryResponse } from "@/api/types";
import { formatTimestamp } from "./format";

/** Builds the Markdown export of the Summary & Notes page from the API response only. */
export function summaryToMarkdown(title: string, s: SummaryResponse): string {
  const out: string[] = [`# ${title}`, "", "## Summary", "", s.summary.trim(), ""];

  if (s.key_takeaways.length) {
    out.push("## Key takeaways", "", ...s.key_takeaways.map((t) => `- ${t}`), "");
  }
  if (s.definitions.length) {
    out.push("## Definitions", "");
    for (const d of s.definitions) {
      const at = d.timestamp !== null ? ` _(at ${formatTimestamp(d.timestamp)})_` : "";
      out.push(`- **${d.term}**: ${d.definition}${at}`);
    }
    out.push("");
  }
  if (s.topics.length) {
    out.push("## Topic notes", "");
    for (const t of s.topics) {
      out.push(`### ${t.title} (${formatTimestamp(t.start)}–${formatTimestamp(t.end)})`, "", t.notes_md.trim(), "");
      if (t.key_points.length) out.push("**Key points**", "", ...t.key_points.map((p) => `- ${p}`), "");
    }
  }
  if (s.revision_notes_md.trim()) {
    out.push("## Revision notes", "", s.revision_notes_md.trim(), "");
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trimEnd() + "\n";
}
