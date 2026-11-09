# REST API

Base URL: `http://localhost:8000/api` · interactive docs: http://localhost:8000/docs (Swagger UI) · schema: `/openapi.json`.

This page describes every endpoint of the finished app: **39 operations** (OpenAPI version 0.1.0). The JSON below shows **shapes** with placeholder values, not real outputs.

**Machine-readable copy:** [openapi.json](openapi.json), generated from the running code by `python -m scripts.export_openapi` (run in `backend/`; same command in PowerShell and bash). Import it into Postman or Insomnia, or re-run the script after an API change. The "Errors" column below lists the status codes each operation declares in that schema; the code names are in [Error codes](#error-codes).

Not implemented (Phase 9, future work): `POST /lectures/{id}/mindmap`, `GET /lectures/{id}/progress`, `GET /dashboard/overview`, adaptive quizzes (`adaptive: true` returns `422 ADAPTIVE_NOT_AVAILABLE`) and the `POST /llmops/eval/run` endpoint (evaluation runs from the CLI, `python -m eval.run`).

## Conventions

- **Auth:** every endpoint except `/health`, `/auth/register` and `/auth/login` needs `Authorization: Bearer <access_token>`.
- **Errors:** always `{"error": {"code": "...", "message": "...", "details": {...}}}`. Each response also has an `X-Request-ID` header that matches the server's log lines.
- **Times:** seconds from the start of the lecture (floats). They always come from transcript segments.
- **Ownership:** a lecture that belongs to another user returns `404 LECTURE_NOT_FOUND`.

## Endpoints

Paths are relative to `/api`. Every error code except `401` (missing or bad token) and `422` (validation) is explained in the sections below.

| Method | Path | Purpose | Success | Errors (from OpenAPI) |
|---|---|---|---|---|
| GET | `/health` | Liveness + database and vector-store checks | 200 | – |
| POST | `/auth/register` | Create an account | 201 | 409, 422 |
| POST | `/auth/login` | Get a JWT | 200 | 401, 422 |
| GET | `/auth/me` | Current user | 200 | 401 |
| POST | `/lectures/upload` | Upload MP3/WAV/MP4/M4A and start processing | 202 | 401, 413, 415, 422, 503 |
| GET | `/lectures` | Your lectures, newest first | 200 | 401 |
| GET | `/lectures/{id}` | Lecture metadata | 200 | 401, 404, 422 |
| GET | `/lectures/{id}/status` | Pipeline stage and progress | 200 | 401, 404, 422 |
| DELETE | `/lectures/{id}` | Delete the lecture, its transcript, outputs, files and vectors | 204 | 401, 404, 422 |
| GET | `/lectures/{id}/transcript` | Timestamped segments | 200 | 401, 404, 409, 422 |
| GET | `/lectures/{id}/transcript/download?format=txt\|srt\|vtt` | File download | 200 | 401, 404, 409, 422 |
| GET | `/lectures/{id}/media` | The original recording, for the media player | 200 / 206 | 401, 404, 422 |
| POST | `/lectures/{id}/summarize` | Summary, takeaways, definitions, topic notes, revision notes (cached) | 200 | 401, 404, 409, 422, 429, 502, 503 |
| GET | `/lectures/{id}/notes` | Topic-wise notes | 200 | 401, 404, 409, 422 |
| POST | `/lectures/{id}/generate-quiz` | Generate a quiz (answers hidden) | 201 | 401, 404, 409, 422, 429, 502, 503 |
| GET | `/lectures/{id}/quizzes` | Your quizzes for the lecture, newest first | 200 | 401, 404, 422 |
| GET | `/quizzes/{quiz_id}` | A quiz without its answers | 200 | 401, 404, 422 |
| POST | `/quizzes/{quiz_id}/submit` | Grade, explain, update topic mastery | 200 | 401, 404, 422, 503 |
| POST | `/lectures/{id}/flashcards` | Generate the flashcard deck (cached) | 200 | 401, 404, 409, 422, 429, 502, 503 |
| GET | `/lectures/{id}/flashcards?due=true` | The deck, optionally only cards due now | 200 | 401, 404, 422 |
| POST | `/flashcards/{card_id}/review` | Record knew / didn't know (Leitner box) | 200 | 401, 404, 422 |
| POST | `/lectures/{id}/ask` | One grounded question (answer + timestamped sources, or a refusal) | 200 | 401, 404, 409, 422, 429, 502, 503 |
| POST | `/lectures/{id}/chat` | Multi-turn chat (`session_id`); follow-ups are rewritten | 200 | 401, 404, 409, 422, 429, 502, 503 |
| GET | `/lectures/{id}/chat` | Your chat sessions for the lecture | 200 | 401, 404, 422 |
| GET | `/lectures/{id}/chat/{session_id}` | Chat history with sources | 200 | 401, 404, 422 |
| GET | `/models` | Answer generators for `model` (cloud, finetuned, base, configured) | 200 | 401 |
| GET | `/llmops/summary` | KPI cards: calls, tokens, actual + equivalent cost, error rate, RTF | 200 | 401, 422 |
| GET | `/llmops/filters` | Values available for the filters | 200 | 401 |
| GET | `/llmops/latency` | M2/M3: p50/p95 per task and model | 200 | 401, 422 |
| GET | `/llmops/qa-latency` | M4: end-to-end question latency per generator | 200 | 401, 422 |
| GET | `/llmops/usage?group=task\|day\|lecture` | M5: tokens, actual and equivalent cost | 200 | 401, 422 |
| GET | `/llmops/transcription` | M1: real-time factor per lecture | 200 | 401, 422 |
| GET | `/llmops/errors` | Error and JSON parse-failure rates, latest failures | 200 | 401, 422 |
| GET | `/llmops/refusals` | Refusals per generator, threshold vs model | 200 | 401, 422 |
| GET | `/llmops/prompts` | Metrics per prompt version | 200 | 401, 422 |
| GET | `/llmops/models` | Model registry (Ollama digests, ASR, embedding, judge, prompts) | 200 | 401 |
| GET | `/llmops/eval/runs` | Evaluation runs, newest first | 200 | 401, 422 |
| GET | `/llmops/eval/runs/{run_id}` | One evaluation run with its items | 200 | 401, 404, 422 |
| GET | `/llmops/eval/compare` | cloud vs finetuned vs base on a golden set, plus SciQ offline runs | 200 | 401, 422 |

## Auth

**POST `/auth/register`** `{"email": "ada@example.com", "password": "at-least-8-chars", "full_name": "Ada"}` → `201` user object. Errors: `409 EMAIL_TAKEN`, `422 VALIDATION_ERROR` (password 8–128 characters and at most 72 bytes).

**POST `/auth/login`** `{"email": "...", "password": "..."}` →
```json
{ "access_token": "<jwt>", "token_type": "bearer", "expires_in": 86400 }
```
Errors: `401 INVALID_CREDENTIALS`, `401 ACCOUNT_DISABLED`.

**GET `/auth/me`** → `{"id", "email", "full_name", "is_active", "created_at"}`. Errors: `401 NOT_AUTHENTICATED`, `401 TOKEN_EXPIRED`, `401 INVALID_TOKEN`.

## Lectures

**POST `/lectures/upload`** (multipart form: `file`, optional `title`) → `202`
```json
{ "lecture_id": "<uuid>", "title": "Intro to Neural Nets", "status": "uploaded", "status_url": "/api/lectures/<uuid>/status" }
```
If no title is given it is built from the file name. Errors:
- `415 UNSUPPORTED_MEDIA_TYPE`: the extension isn't allowed, the content type doesn't match, or the file has no readable audio track.
- `413 FILE_TOO_LARGE`: over `MAX_UPLOAD_MB`.
- `503 FFMPEG_NOT_FOUND`: ffmpeg is not installed on the server.

**GET `/lectures/{id}/status`**
```json
{ "status": "generating", "progress": 85, "stage_detail": "Generating summary: notes 2 of 4", "error": null }
```
Status values (see [architecture.md](architecture.md#status-values)):
- `uploaded`, `extracting_audio`, `transcribing`: processing.
- `indexing`: chunks of the transcript are embedded for search (the transcript is already readable).
- `transcribed`: the transcript is available.
- `generating`: summary and notes in progress.
- `ready`: everything is available.
- `failed`: see `error`.

If `status` is `transcribed` and `error` is not null, the summary failed and can be retried.

**GET `/lectures/{id}`** → `{"id", "title", "original_filename", "status", "progress", "stage_detail", "error", "duration_sec", "language", "size_bytes", "created_at", "updated_at"}`.

**DELETE `/lectures/{id}`** → `204`. Removes the rows (segments, outputs and pipeline runs cascade) and the stored files. The `llm_calls` rows are kept for metrics, unlinked from the lecture.

## Transcript

**GET `/lectures/{id}/transcript`**
```json
{ "lecture_id": "<uuid>", "duration_sec": 291.8, "language": "English",
  "segments": [ { "id": 0, "start": 0.0, "end": 2.3, "text": "..." } ] }
```
Errors: `409 LECTURE_NOT_READY` before the transcript exists. Its `details` holds the current `status` and `progress`.

**GET `/lectures/{id}/transcript/download?format=srt`** returns a file (`Content-Disposition: attachment`):
- `txt`: `[MM:SS] text` lines
- `srt`: numbered SubRip cues, `HH:MM:SS,mmm`
- `vtt`: WebVTT, `HH:MM:SS.mmm`

An invalid format returns `422`.

## Media

**GET `/lectures/{id}/media`** returns the uploaded recording itself (`Content-Disposition: inline`), so the transcript page can play it and seek to a segment's timestamp.
- **Content-Type** comes from the stored file's extension: `audio/mpeg` (mp3), `audio/wav` (wav), `video/mp4` (mp4), `audio/mp4` (m4a).
- **Range requests** (`Range: bytes=…`) are supported and answered with `206 Partial Content`.
- **Auth:** like every endpoint, it needs the Bearer header, so a plain `<audio src>` can't call it. The frontend fetches it with axios as a blob (only after the user presses play) and plays an object URL. That's fine for short demo lectures. Long recordings would need streaming with a short-lived media token instead.
- **Errors:** `404 LECTURE_NOT_FOUND` (unknown or not yours), `404 MEDIA_NOT_FOUND` (the lecture has no stored file, or the file was removed from `storage/`).

## Summary and notes

**POST `/lectures/{id}/summarize`**: the body is optional, default `{"regenerate": false}`.
```json
{
  "lecture_id": "<uuid>",
  "summary": "…",
  "key_takeaways": ["…"],
  "definitions": [ { "term": "…", "definition": "…", "timestamp": 49.0 } ],
  "topics": [ { "title": "…", "start": 0.0, "end": 168.0, "notes_md": "- …", "key_points": ["…"] } ],
  "revision_notes_md": "- …",
  "meta": {
    "provider": "groq", "model": "openai/gpt-oss-120b", "model_version": "…",
    "prompt_version": "summary@v1",
    "prompt_versions": { "topics": "topics@v1", "notes": "notes@v1", "summary": "summary@v1" },
    "mode": "single_pass", "windows": 1, "llm_calls": 4,
    "input_tokens": 0, "output_tokens": 0, "llm_latency_ms": 0.0, "generated_at": "…"
  },
  "cached": false
}
```
- **When it generates:**
  - With a cached result and `regenerate: false`, it returns immediately with `"cached": true`.
  - Otherwise it runs the LLM synchronously. For a long lecture on the free tier this can take minutes.
- **Field notes:**
  - `definitions[].timestamp` is `null` when the model pointed at a segment outside the part of the lecture it was given.
  - `meta.mode` is `single_pass` or `map_reduce`. The `meta` numbers are real counts from that run (see [summarization.md](summarization.md)).
- **Errors:**
  - `409 LECTURE_NOT_READY`: there is no transcript yet.
  - `409 GENERATION_IN_PROGRESS`: a generation is already running.
  - `422 TRANSCRIPT_EMPTY`: no speech was recognised.
  - `429 RATE_LIMITED`: Groq is still rate-limiting after retries. There is no paid fallback.
  - `503 MODEL_UNAVAILABLE`, `503 PROVIDER_NOT_CONFIGURED`.
  - `502 LLM_OUTPUT_INVALID`: the model returned invalid JSON twice.

**GET `/lectures/{id}/notes`**
```json
{ "lecture_id": "<uuid>",
  "topics": [ { "title": "…", "start": 0.0, "end": 168.0, "notes_md": "- …", "key_points": ["…"] } ],
  "meta": { "...": "same as above" } }
```
Errors: `409 NOTES_NOT_GENERATED` (call `POST /summarize`) and `409 GENERATION_IN_PROGRESS`.

## Quizzes

How questions are generated, validated and graded: [quizzes.md](quizzes.md). Quizzes and flashcards need the topic notes, so they return `409 NOTES_NOT_GENERATED` until `POST /summarize` has run.

**POST `/lectures/{id}/generate-quiz`**: every field is optional.
```json
{ "num_questions": 10, "types": ["mcq", "true_false", "short_answer"], "difficulty": "medium", "topics": null, "adaptive": false }
```
`difficulty` is `easy | medium | hard | mixed`, and `topics` lists topic titles from `/notes` (null means all). → `201`
```json
{ "quiz_id": "<uuid>", "lecture_id": "<uuid>", "difficulty": "medium", "created_at": "…", "attempts": 0,
  "questions": [
    { "id": "q1", "type": "mcq", "difficulty": "medium", "topic": "…", "question": "…", "options": ["…", "…", "…", "…"] },
    { "id": "q2", "type": "true_false", "difficulty": "medium", "topic": "…", "question": "…", "options": null }
  ],
  "meta": { "provider": "groq", "model": "openai/gpt-oss-120b", "prompt_version": "quiz@v1",
            "requested": 10, "generated": 10, "invalid_items": 0, "invalid_reasons": {},
            "regeneration_requests": 0, "batches": 1, "llm_calls": 1,
            "input_tokens": 0, "output_tokens": 0, "llm_latency_ms": 0.0, "generated_at": "…" } }
```
- **Answers:** none are included here, and no explanations either. Each call creates a new quiz.
- **Errors:**
  - `422 VALIDATION_ERROR`: `num_questions` is above `QUIZ_MAX_QUESTIONS`, a type is unknown, or a topic is unknown (`details.available` lists the valid ones).
  - `422 ADAPTIVE_NOT_AVAILABLE`: comes in Phase 9.
  - `409 LECTURE_NOT_READY`, `409 NOTES_NOT_GENERATED`.
  - `429 RATE_LIMITED`, `503 MODEL_UNAVAILABLE`.
  - `502 QUIZ_GENERATION_FAILED`: no valid question at all.

**GET `/quizzes/{quiz_id}`** returns the same shape, with `attempts` counting your submissions. **GET `/lectures/{id}/quizzes`** → `[{"quiz_id", "difficulty", "num_questions", "created_at", "attempts", "best_percent"}]`.

**POST `/quizzes/{quiz_id}/submit`**
```json
{ "answers": { "q1": "B", "q2": true, "q3": "free text" } }
```
- **MCQ:** a letter A–D or the option text.
- **True/false:** a boolean, or the string `"true"` / `"false"`.
- **Unanswered:** a missing question counts as wrong.

```json
{ "attempt_id": "<uuid>", "quiz_id": "<uuid>", "score": 7, "total": 10, "percent": 70.0,
  "results": [ { "id": "q1", "type": "mcq", "topic": "…", "question": "…", "your_answer": "B", "correct": true,
                 "score": 1.0, "correct_answer": "B", "explanation": "…", "timestamp": 845.0,
                 "graded_by": "rule", "feedback": null } ],
  "topics": [ { "topic": "…", "correct": 2, "total": 3, "mastery": 0.67 } ],
  "weak_topics": ["…"], "suggested_next_difficulty": "medium" }
```
- **`graded_by`:**
  - `rule` for MCQ and true/false.
  - `llm` for short answers.
  - `embedding` when the LLM grader failed and the similarity fallback was used.
- **`timestamp`:** where the lecture covers the question.
- **`mastery`:** the topic's moving average after this attempt.
- **Errors:**
  - `422 VALIDATION_ERROR`: `details.unknown` lists unknown question ids, `details.invalid` lists answers of the wrong type.
  - `404 QUIZ_NOT_FOUND`.
  - `503 GRADING_UNAVAILABLE`: the LLM grader and the embedding fallback both failed.

## Flashcards

**POST `/lectures/{id}/flashcards`**: the body is optional, default `{"regenerate": false}`.
```json
{ "lecture_id": "<uuid>", "total": 15, "due": 15, "cached": false,
  "cards": [ { "id": "<uuid>", "kind": "concept", "front": "…?", "back": "…", "topic": "…", "timestamp": 47.0,
               "box": 1, "due_at": "…", "due": true, "last_reviewed_at": null } ],
  "meta": { "prompt_version": "flashcards@v1", "definition_cards": 0, "concept_cards": 15,
            "dropped": { "duplicate": 0 }, "batches": 1, "llm_calls": 1, "...": "…" } }
```
- **`kind`:** `definition` cards come from the summary's definitions, with no LLM call. `concept` cards are written from the transcript.
- **Cached deck:** a second call returns the stored deck with `"cached": true` and `"meta": null`.
- **Regenerating:** `regenerate: true` replaces the deck and resets review progress.
- **Errors:** as for quizzes.

**GET `/lectures/{id}/flashcards?due=true`** returns the same shape without `cached` or `meta`. With `due=false` (the default) it returns every card.

**POST `/flashcards/{card_id}/review`** `{"knew": true}` → the updated card. Knowing a card moves it up one box (at most 5). Box 2 is due again in 1 day, box 3 in 3 days, box 4 in 7 and box 5 in 14. Not knowing it sends the card back to box 1, due now. Errors: `404 FLASHCARD_NOT_FOUND`, `422 VALIDATION_ERROR`.

## Ask and chat

How retrieval, the threshold, refusals and generators work: [rag.md](rag.md). These endpoints need a transcript (`409 LECTURE_NOT_READY` otherwise), not a summary. A lecture without a search index is indexed on its first question.

**POST `/lectures/{id}/ask`**
```json
{ "question": "What are the two types of serverless architecture?", "model": "cloud" }
```
`model` is `"cloud"` (default), `"finetuned"` or `"base"`, or a name added via `ANSWER_GENERATORS` (see `GET /models`). →
```json
{ "answer": "… [C1].", "answerable": true,
  "sources": [ { "chunk_id": "C1", "chunk_idx": 0, "start": 0.0, "end": 86.4, "excerpt": "…", "score": 0.79, "cited": true } ],
  "meta": { "generator": "cloud", "provider": "groq", "model": "…", "prompt_version": "rag_answer@v1",
            "rewritten_question": null, "refusal_reason": null, "top_score": 0.79, "scores": [0.79, 0.6],
            "min_score": 0.5, "top_k": 5, "retrieval_ms": 0.0, "latency_ms": 0.0, "llm_calls": 1,
            "input_tokens": 0, "output_tokens": 0, "citations_dropped": [], "citation_check": "ok",
            "indexed_now": false, "chunks": 4 } }
```
- **Refusals:** a refusal has `answerable: false`, `refusal_reason` `below_threshold` (no LLM call) or `not_in_chunks` (the model found no answer), and an answer like "This isn't covered in the lecture. The closest parts of the lecture are at 00:00–01:26, …". Its `sources` are the closest chunks, with `cited: false`.
- **Timestamps:** `start`/`end` are seconds from the transcript segments.
- **Errors:**
  - `422 UNKNOWN_GENERATOR` (`details.available`), `422 VALIDATION_ERROR` (empty, or longer than `RAG_MAX_QUESTION_CHARS`).
  - `409 LECTURE_NOT_READY`, `409 INDEXING_IN_PROGRESS`.
  - `429 RATE_LIMITED`.
  - `503 MODEL_UNAVAILABLE`: for `finetuned`/`base`, Ollama isn't running or the model isn't installed; the message says how to fix it.
  - `502 LLM_OUTPUT_INVALID`.

**POST `/lectures/{id}/chat`**
```json
{ "message": "Can you give an example of the first one?", "session_id": "<uuid or null>", "model": "cloud" }
```
→ the `/ask` shape plus `session_id`, `message_id`, `question` and `rewritten_question` (the standalone question used for retrieval; `null` on the first turn). Send `session_id` back to continue. Errors are as for `/ask`, plus `404 CHAT_SESSION_NOT_FOUND`.

**GET `/lectures/{id}/chat`** → `[{"session_id", "title", "created_at", "messages"}]`. **GET `/lectures/{id}/chat/{session_id}`** → `{"session_id", "lecture_id", "title", "created_at", "messages": [{"id", "role", "content", "sources", "answerable", "refusal_reason", "model", "created_at"}]}`. `refusal_reason` (added in Phase 8) is `below_threshold` or `not_in_chunks` on a refused assistant message, read from `qa_logs`, and `null` otherwise, so a reopened chat can show why a question was refused.

**GET `/models`** → `[{"name": "cloud", "provider": "groq", "model": "openai/gpt-oss-120b", "description": "…", "version": "…", "last_used_at": "…", "details": null}, …]`. Phase 11 added the optional `version` (the last model string the provider returned; for Ollama `tag@sha256:<digest>`), `last_used_at`, and for `finetuned` `details.finetune` (base model + revision, dataset + revision, GGUF size, Hub repo; read from `finetune/results/training.json`). This endpoint only reads the database, so the Ask page stays fast.

## LLMOps (Phase 11)

How every metric is defined: [llmops.md](llmops.md). Metrics are **system-wide** (all users' calls) for any logged-in user.

**Filters** (query parameters, all optional): `date_from`, `date_to` (UTC days, inclusive, `YYYY-MM-DD`), `task` (an `llm_calls` task), `generator` (`cloud | finetuned | base | …`: calls made with that generator's provider + model; for qa_logs metrics, that generator's questions), `include_eval` (default `false`: tasks `eval_*` from the harness are left out).

**GET `/llmops/summary`**
```json
{ "filters": {"date_from": null, "date_to": null, "task": null, "generator": null, "include_eval": false},
  "calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
  "cost_usd": 0.0, "cost_unknown_calls": 0, "equivalent_cost_usd": 0.0, "unpriced_calls": 0,
  "failed_calls": 0, "error_rate": 0.0, "json_invalid_calls": 0, "parse_failure_rate": 0.0,
  "rtf_overall": 0.0, "transcriptions": 0, "questions": 0,
  "qa_latency": {"n": 0, "p50_ms": 0.0, "p95_ms": 0.0, "mean_ms": 0.0},
  "first_call_at": "…", "last_call_at": "…", "pricing_checked": "2026-11-06" }
```
The other metric endpoints return lists of rows: `/latency` `[{task, provider, model, n, p50_ms, p95_ms, mean_ms}]`; `/qa-latency` `[{generator, n, p50_ms, p95_ms, mean_ms, answered, refused_by_model, refused_by_threshold, retrieval}]`; `/usage` `[{key, label, calls, input_tokens, output_tokens, total_tokens, cost_usd, cost_unknown_calls, equivalent_cost_usd, unpriced_calls}]`; `/transcription` `{runs: [{lecture_id, title, started_at, audio_sec, processing_sec, rtf}], rtf_overall, rtf_median, …}`; `/errors` `{requests, failed, error_rate, json_invalid, by_task: […], recent: […]}`; `/refusals` `[{generator, questions, answered, below_threshold, not_in_chunks, errors, refused, refusal_rate, threshold_share_of_refusals}]`; `/prompts` `[{prompt_version, task, requests, p50_ms, p95_ms, error_rate, parse_failure_rate, mean_input_tokens, mean_output_tokens}]`.

**GET `/llmops/models`** → `{"ollama_reachable", "ollama_url", "generators": [{name, provider, model, version, digest, size_bytes, available, details}], "others": [asr, embedding, eval judge, quiz grader], "prompts": [{id, version, tag}]}`. It asks Ollama for its tag list (cached 5 min).

**GET `/llmops/eval/runs`** → runs, newest first (`source` = `harness` or `offline_import`, `metrics` = the run's `metrics_json`). **GET `/llmops/eval/runs/{id}`** adds `items`. **GET `/llmops/eval/compare?golden_set=`** → the latest finished harness run per generator for one golden set (default: the most recent), its `retrieval` run, and the latest `offline` SciQ runs.

Errors: `401`, `422 VALIDATION_ERROR` (`date_from` after `date_to`, bad `group`), `422 UNKNOWN_GENERATOR`, `404 EVAL_RUN_NOT_FOUND`.

## Error codes

| HTTP | Code | Meaning |
|---|---|---|
| 401 | `NOT_AUTHENTICATED`, `TOKEN_EXPIRED`, `INVALID_TOKEN`, `INVALID_CREDENTIALS`, `ACCOUNT_DISABLED` | Auth problems |
| 404 | `NOT_FOUND`, `LECTURE_NOT_FOUND`, `MEDIA_NOT_FOUND`, `QUIZ_NOT_FOUND`, `FLASHCARD_NOT_FOUND`, `CHAT_SESSION_NOT_FOUND`, `EVAL_RUN_NOT_FOUND` | Unknown route, or not yours |
| 409 | `EMAIL_TAKEN`, `LECTURE_NOT_READY`, `GENERATION_IN_PROGRESS`, `NOTES_NOT_GENERATED`, `INDEXING_IN_PROGRESS` | State conflicts |
| 413 | `FILE_TOO_LARGE` | Upload over `MAX_UPLOAD_MB` |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Not MP3/WAV/MP4/M4A or no audio track |
| 422 | `VALIDATION_ERROR`, `TRANSCRIPT_EMPTY`, `MEDIA_ERROR`, `ADAPTIVE_NOT_AVAILABLE`, `UNKNOWN_GENERATOR` | Bad input / nothing to process |
| 429 | `RATE_LIMITED` | Provider rate limit after retries (`Retry-After` header when known) |
| 500 | `INTERNAL_ERROR` | Unexpected; `details.error_type` names the exception |
| 502 | `LLM_ERROR`, `LLM_OUTPUT_INVALID`, `QUIZ_GENERATION_FAILED` | Provider error / invalid JSON twice / no valid question |
| 503 | `MODEL_UNAVAILABLE`, `PROVIDER_NOT_CONFIGURED`, `FFMPEG_NOT_FOUND`, `GRADING_UNAVAILABLE` | Model or tool not available |

## Try it with curl

These examples use `curl` on macOS/Linux. On Windows PowerShell, type `curl.exe` instead of `curl`, and use the `$TOKEN` syntax shown in the last line.

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","password":"correct-horse-battery"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -s -X POST http://localhost:8000/api/lectures/upload -H "Authorization: Bearer $TOKEN" -F "file=@lecture.mp3"
curl -s http://localhost:8000/api/lectures/<id>/status -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://localhost:8000/api/lectures/<id>/summarize -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"regenerate": false}'
curl -s "http://localhost:8000/api/lectures/<id>/transcript/download?format=srt" -H "Authorization: Bearer $TOKEN" -o lecture.srt
```
PowerShell token: `$TOKEN = (Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/login -ContentType application/json -Body '{"email":"ada@example.com","password":"correct-horse-battery"}').access_token`.

The complete scripted flows are in `backend/scripts/manual_phase4.*` to `manual_phase7.*`.
