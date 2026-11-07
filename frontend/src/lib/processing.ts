import type { LectureStatus, LectureStatusOut } from "@/api/types";

/** Stepper model for the processing page (statuses from backend/app/models/lecture.py). */
export const STEPS = [
  { label: "Uploaded", hint: "File received and checked" },
  { label: "Extracting audio", hint: "Converting to 16 kHz mono with ffmpeg" },
  { label: "Transcribing", hint: "Speech to text with timestamps" },
  { label: "Indexing for search", hint: "Embedding transcript chunks for the Ask tab" },
  { label: "Writing summary & notes", hint: "Summary, takeaways, definitions and topic notes" },
  { label: "Ready", hint: "Everything is available" },
] as const;

// Progress values from backend/app/workers/pipeline.py (P_EXTRACT=5, P_TRANSCRIBE_START=10).
const P_TRANSCRIBE_START = 10;

export type StepState = "done" | "active" | "failed" | "todo";

export interface StepModel {
  /** Index of the current step; STEPS.length when everything is done. */
  current: number;
  failed: boolean;
}

/** Maps /status to the stepper. A failed lecture keeps its progress, which tells us the stage. */
export function stepModel(s: LectureStatusOut): StepModel {
  const order: Record<Exclude<LectureStatus, "failed">, number> = {
    uploaded: 0,
    extracting_audio: 1,
    transcribing: 2,
    indexing: 3,
    transcribed: 4,
    generating: 4,
    ready: STEPS.length,
  };
  if (s.status === "failed") return { current: s.progress >= P_TRANSCRIBE_START ? 2 : 1, failed: true };
  if (s.status === "transcribed" && s.error) return { current: 4, failed: true };
  return { current: order[s.status], failed: false };
}

