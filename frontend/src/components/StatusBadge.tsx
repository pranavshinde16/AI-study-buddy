import type { LectureStatus } from "@/api/types";
import { Badge } from "@/components/ui/badge";

const LABELS: Record<LectureStatus, string> = {
  uploaded: "Uploaded",
  extracting_audio: "Extracting audio",
  transcribing: "Transcribing",
  indexing: "Indexing",
  transcribed: "Transcribed",
  generating: "Writing notes",
  ready: "Ready",
  failed: "Failed",
};

export function StatusBadge({ status, error }: { status: LectureStatus; error?: string | null }) {
  if (status === "ready") return <Badge variant="success">{LABELS[status]}</Badge>;
  if (status === "failed") return <Badge variant="destructive">{LABELS[status]}</Badge>;
  if (status === "transcribed") return <Badge variant={error ? "warning" : "secondary"}>{error ? "Notes failed" : LABELS[status]}</Badge>;
  return <Badge>{LABELS[status] ?? status}</Badge>;
}
