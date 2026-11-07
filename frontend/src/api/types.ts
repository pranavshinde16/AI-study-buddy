/**
 * TypeScript mirrors of the backend's Pydantic schemas (backend/app/schemas/*.py).
 * Keep these in sync when a schema changes (CLAUDE.md rule 8). UUIDs and datetimes arrive as strings.
 */

// ---------------------------------------------------------------- errors (schemas/errors.py)
export interface ErrorEnvelope {
  error: { code: string; message: string; details: Record<string, unknown> };
}

// ---------------------------------------------------------------- auth (schemas/auth.py)
export interface RegisterRequest {
  email: string;
  password: string;
  full_name?: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  /** Seconds until the token expires. */
  expires_in: number;
}

export interface UserOut {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string;
}

// ---------------------------------------------------------------- lectures (schemas/lectures.py, models/lecture.py)
export type LectureStatus =
  | "uploaded"
  | "extracting_audio"
  | "transcribing"
  | "indexing"
  | "transcribed"
  | "generating"
  | "ready"
  | "failed";

export interface UploadResponse {
  lecture_id: string;
  title: string;
  status: LectureStatus;
  status_url: string;
}

export interface LectureOut {
  id: string;
  title: string;
  original_filename: string | null;
  status: LectureStatus;
  progress: number;
  stage_detail: string | null;
  error: string | null;
  duration_sec: number | null;
  language: string | null;
  size_bytes: number | null;
  created_at: string;
  updated_at: string;
}

export interface LectureStatusOut {
  status: LectureStatus;
  progress: number;
  stage_detail: string | null;
  error: string | null;
}

export interface SegmentOut {
  id: number;
  start: number;
  end: number;
  text: string;
}

export interface TranscriptOut {
  lecture_id: string;
  duration_sec: number | null;
  language: string | null;
  segments: SegmentOut[];
}

export type TranscriptFormat = "txt" | "srt" | "vtt";

// ---------------------------------------------------------------- summaries (schemas/summaries.py)
export interface SummarizeRequest {
  regenerate: boolean;
}

export interface DefinitionOut {
  term: string;
  definition: string;
  timestamp: number | null;
}

export interface TopicOut {
  title: string;
  start: number;
  end: number;
  notes_md: string;
  key_points: string[];
}

export interface GenerationMeta {
  provider: string | null;
  model: string | null;
  model_version: string | null;
  prompt_version: string | null;
  prompt_versions: Record<string, string>;
  mode: string | null;
  windows: number | null;
  llm_calls: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  llm_latency_ms: number | null;
  generated_at: string | null;
}

export interface SummaryResponse {
  lecture_id: string;
  summary: string;
  key_takeaways: string[];
  definitions: DefinitionOut[];
  topics: TopicOut[];
  revision_notes_md: string;
  meta: GenerationMeta;
  cached: boolean;
}

export interface NotesResponse {
  lecture_id: string;
  topics: TopicOut[];
  meta: GenerationMeta;
}
