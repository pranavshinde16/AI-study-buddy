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

// ---------------------------------------------------------------- quizzes (schemas/quizzes.py)
export type QuestionType = "mcq" | "true_false" | "short_answer";
export type DifficultyIn = "easy" | "medium" | "hard" | "mixed";
export type Difficulty = "easy" | "medium" | "hard";

export interface GenerateQuizRequest {
  num_questions: number;
  types: QuestionType[];
  difficulty: DifficultyIn;
  topics: string[] | null;
  adaptive: boolean;
}

export interface QuestionOut {
  id: string;
  type: QuestionType;
  difficulty: string;
  topic: string | null;
  question: string;
  /** mcq only: 4 options; answer with the letter A-D. */
  options: string[] | null;
}

export interface QuizMeta {
  provider: string | null;
  model: string | null;
  model_version: string | null;
  prompt_version: string | null;
  requested: number | null;
  generated: number | null;
  invalid_items: number | null;
  invalid_reasons: Record<string, number>;
  regeneration_requests: number | null;
  batches: number | null;
  llm_calls: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  llm_latency_ms: number | null;
  generated_at: string | null;
}

export interface QuizOut {
  quiz_id: string;
  lecture_id: string;
  difficulty: string | null;
  created_at: string;
  questions: QuestionOut[];
  attempts: number;
  meta: QuizMeta;
}

export interface QuizSummaryOut {
  quiz_id: string;
  difficulty: string | null;
  num_questions: number;
  created_at: string;
  attempts: number;
  best_percent: number | null;
}

export type AnswerValue = boolean | string | null;

export interface SubmitQuizRequest {
  answers: Record<string, AnswerValue>;
}

export interface QuestionResult {
  id: string;
  type: QuestionType;
  topic: string | null;
  question: string;
  your_answer: AnswerValue;
  correct: boolean;
  score: number;
  /** mcq: letter; true_false: boolean; short_answer: model answer. */
  correct_answer: boolean | string;
  explanation: string | null;
  timestamp: number | null;
  graded_by: "rule" | "llm" | "embedding";
  feedback: string | null;
}

export interface TopicScore {
  topic: string;
  correct: number;
  total: number;
  mastery: number;
}

export interface SubmitQuizResponse {
  attempt_id: string;
  quiz_id: string;
  score: number;
  total: number;
  percent: number;
  results: QuestionResult[];
  topics: TopicScore[];
  weak_topics: string[];
  suggested_next_difficulty: Difficulty;
}

// ---------------------------------------------------------------- flashcards (schemas/flashcards.py)
export interface FlashcardOut {
  id: string;
  kind: "definition" | "concept";
  front: string;
  back: string;
  topic: string | null;
  timestamp: number | null;
  /** Leitner box 1-5. */
  box: number;
  due_at: string;
  due: boolean;
  last_reviewed_at: string | null;
}

export interface DeckMeta {
  provider: string | null;
  model: string | null;
  model_version: string | null;
  prompt_version: string | null;
  definition_cards: number | null;
  concept_cards: number | null;
  dropped: Record<string, number>;
  batches: number | null;
  llm_calls: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  llm_latency_ms: number | null;
  generated_at: string | null;
}

export interface DeckOut {
  lecture_id: string;
  total: number;
  due: number;
  cards: FlashcardOut[];
  /** POST only. */
  cached?: boolean | null;
  /** POST only, when a new deck was generated. */
  meta?: DeckMeta | null;
}

// ---------------------------------------------------------------- ask / chat (schemas/rag.py)
export type RefusalReason = "below_threshold" | "not_in_chunks";

export interface SourceOut {
  chunk_id: string;
  chunk_idx: number;
  start: number;
  end: number;
  excerpt: string;
  score: number;
  cited: boolean;
}

export interface AskMeta {
  generator: string;
  provider: string | null;
  model: string | null;
  prompt_version: string | null;
  rewritten_question: string | null;
  refusal_reason: RefusalReason | null;
  top_score: number | null;
  scores: number[];
  min_score: number;
  top_k: number;
  retrieval_ms: number;
  latency_ms: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  citations_dropped: string[];
  citation_check: string;
  indexed_now: boolean;
  chunks: number;
}

export interface AskResponse {
  answer: string;
  answerable: boolean;
  sources: SourceOut[];
  meta: AskMeta;
}

export interface ChatRequest {
  message: string;
  session_id: string | null;
  model: string;
}

export interface ChatResponse extends AskResponse {
  session_id: string;
  message_id: string;
  question: string;
  rewritten_question: string | null;
}

export interface ChatMessageOut {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: SourceOut[];
  answerable: boolean | null;
  refusal_reason: RefusalReason | null;
  model: string | null;
  created_at: string;
}

export interface ChatHistoryOut {
  session_id: string;
  lecture_id: string;
  title: string | null;
  created_at: string;
  messages: ChatMessageOut[];
}

export interface ChatSessionOut {
  session_id: string;
  title: string | null;
  created_at: string;
  messages: number;
}

export interface GeneratorOut {
  name: string;
  provider: string;
  model: string;
  description: string;
  /** Phase 11: last model string the provider returned (Ollama: tag@sha256:<digest>). */
  version?: string | null;
  last_used_at?: string | null;
  details?: Record<string, unknown> | null;
}

// ------------------------------------------------------------------ LLMOps (Phase 11)
// Mirrors backend/app/schemas/llmops.py.

export interface LlmOpsFilters {
  date_from?: string | null; // YYYY-MM-DD (UTC, inclusive)
  date_to?: string | null;
  task?: string | null;
  generator?: string | null;
  include_eval?: boolean;
}

export interface LatencyStats {
  n: number;
  p50_ms: number | null;
  p95_ms: number | null;
  mean_ms: number | null;
}

export interface LlmOpsSummaryOut {
  filters: {
    date_from: string | null;
    date_to: string | null;
    task: string | null;
    generator: string | null;
    include_eval: boolean;
  };
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  cost_unknown_calls: number;
  equivalent_cost_usd: number;
  unpriced_calls: number;
  failed_calls: number;
  error_rate: number | null;
  json_invalid_calls: number;
  parse_failure_rate: number | null;
  rtf_overall: number | null;
  transcriptions: number;
  questions: number;
  qa_latency: LatencyStats;
  first_call_at: string | null;
  last_call_at: string | null;
  pricing_checked: string;
}

export interface TaskLatencyOut extends LatencyStats {
  task: string;
  provider: string;
  model: string;
}

export interface QALatencyOut extends LatencyStats {
  generator: string;
  answered: LatencyStats;
  refused_by_model: LatencyStats;
  refused_by_threshold: LatencyStats;
  retrieval: LatencyStats;
}

export type UsageGroup = "task" | "lecture" | "day";

export interface UsageRowOut {
  key: string;
  label: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  cost_unknown_calls: number;
  equivalent_cost_usd: number;
  unpriced_calls: number;
}

export interface TranscriptionRunOut {
  lecture_id: string;
  title: string | null;
  started_at: string;
  audio_sec: number;
  processing_sec: number;
  rtf: number;
}

export interface TranscriptionOut {
  runs: TranscriptionRunOut[];
  n: number;
  total_audio_sec: number;
  total_processing_sec: number;
  rtf_overall: number | null;
  rtf_median: number | null;
}

export interface TaskErrorsOut {
  task: string;
  requests: number;
  failed: number;
  json_invalid: number;
  repair_failed: number;
  rate_limited: number;
  error_rate: number | null;
  parse_failure_rate: number | null;
}

export interface RecentErrorOut {
  ts: string;
  task: string;
  provider: string;
  model: string;
  status: string;
  error_type: string | null;
  error_message: string | null;
  prompt_version: string | null;
  attempt: number;
}

export interface ErrorsOut {
  requests: number;
  failed: number;
  error_rate: number | null;
  json_invalid: number;
  by_task: TaskErrorsOut[];
  recent: RecentErrorOut[];
}

export interface RefusalsOut {
  generator: string;
  questions: number;
  answered: number;
  below_threshold: number;
  not_in_chunks: number;
  errors: number;
  refused: number;
  refusal_rate: number | null;
  threshold_share_of_refusals: number | null;
}

export interface PromptMetricsOut extends LatencyStats {
  prompt_version: string;
  prompt_id: string | null;
  task: string;
  requests: number;
  error_rate: number | null;
  parse_failure_rate: number | null;
  mean_input_tokens: number | null;
  mean_output_tokens: number | null;
}

export interface FilterOptionsOut {
  tasks: string[];
  eval_tasks: string[];
  generators: string[];
  generators_with_questions: string[];
  first_call_at: string | null;
  last_call_at: string | null;
}

export interface FinetuneDetails {
  source_file: string | null;
  base_model: string | null;
  base_model_revision: string | null;
  loaded_from: string | null;
  dataset: string | null;
  dataset_revision: string | null;
  train_examples: number | null;
  validation_examples: number | null;
  method: string | null;
  lora: Record<string, unknown> | null;
  gguf_file: string | null;
  gguf_bytes: number | null;
  trained_at: string | null;
  gpu: string | null;
  hub_repo: string | null;
}

export interface RegistryGeneratorOut {
  kind: string;
  name: string;
  provider: string;
  model: string;
  description: string;
  version: string | null;
  last_used_at: string | null;
  digest: string | null;
  size_bytes: number | null;
  available: boolean | null;
  details: {
    modified_at?: string | null;
    family?: string | null;
    parameter_size?: string | null;
    quantization_level?: string | null;
    format?: string | null;
    finetune?: FinetuneDetails;
  };
}

export interface RegistryOtherOut {
  kind: string;
  name: string;
  provider: string;
  model: string;
  version: string | null;
  last_used_at: string | null;
  revision?: string | null;
  note?: string | null;
}

export interface ModelRegistryOut {
  ollama_reachable: boolean | null;
  ollama_url: string;
  generators: RegistryGeneratorOut[];
  others: RegistryOtherOut[];
  prompts: { id: string; version: string; tag: string }[];
}

/** eval_runs.metrics_json: shape depends on the run (generator / retrieval / offline import). */
export type EvalMetrics = Record<string, unknown>;

export interface EvalRunOut {
  id: string;
  golden_set: string;
  generator: string;
  model: string | null;
  source: "harness" | "offline_import" | string;
  lecture_id: string | null;
  lecture_title: string | null;
  n_items: number | null;
  status: string;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  prompt_versions: Record<string, unknown> | null;
  config: Record<string, unknown> | null;
  metrics: EvalMetrics | null;
}

export interface EvalCompareOut {
  golden_set: string | null;
  golden_sets: string[];
  retrieval: EvalRunOut | null;
  generators: EvalRunOut[];
  offline: EvalRunOut[];
}
