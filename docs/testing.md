# Testing (Phase 13)

> Every number on this page was copied from real test output on **2026-11-09** (Windows 11, Python 3.12.10,
> Node 24.20.0, ffmpeg 9.0.2). Re-run the commands below to reproduce them.

## 1. Results at a glance

| Suite | Command | Result |
|---|---|---|
| Backend unit + API tests | `pytest -q -W error --cov=app --cov=eval --cov=scripts` | **317 passed**, 0 failed, 0 skipped, 89.9 s |
| Backend coverage, `app/` (the application) | same run | **95 %** (5,047 statements, 267 missed) |
| Backend coverage, `app/services/` (business logic) | same run | **94 %** (3,482 statements, 203 missed) |
| Backend coverage, `app/api/` (routers + dependencies) | same run | **96 %** (319 statements, 12 missed) |
| Backend coverage, everything measured (`app` + `eval` + `scripts`) | same run | **88 %** (5,548 statements, 642 missed) |
| Fine-tuning helpers | `pytest -q tests` in `finetune/` | **22 passed** |
| Frontend component + unit tests | `npm test` (Vitest 5.0.5) | **60 passed** in 11 files |
| Frontend types | `npm run typecheck` (TypeScript 5.9.3) | clean (exit 0) |
| Frontend lint | `npm run lint` (ESLint 10.13.0) | clean (exit 0) |

`-W error` turns every Python warning into a failure, so the backend run is also warning-free.

The combined backend figure (88 %) is lower than the `app/` figure because it includes the command-line tools in
`eval/` and `scripts/` (25 % together). Those are thin wrappers that call real providers or a real database, and they
are checked by hand (§4).

## 2. How to run the tests

The commands are the same in PowerShell and bash/zsh once the virtual environment is active
(`.\.venv\Scripts\Activate.ps1` on Windows, `source .venv/bin/activate` on macOS/Linux).

```bash
cd backend
pytest -q                                                    # quick run
pytest -q -W error --cov=app --cov-report=term-missing       # with coverage and missed line numbers

cd ../finetune
python -m pytest -q tests                                    # uses the backend venv or requirements-local.txt

cd ../frontend
npm test
npm run typecheck
npm run lint
```

**No test touches the network.** The backend has an autouse fixture that fails any test opening a non-loopback
connection (`tests/test_network_guard.py` proves it works). The frontend blocks `fetch`/XHR in
`src/test/setup.ts` and answers API calls from `src/test/mockApi.ts`. No Groq key is needed to run the tests.

## 3. What each test area covers

### Backend (`backend/tests/`, 317 tests)

Tests run on in-memory SQLite with fake providers from `tests/fakes.py`: `FakeASRProvider` (speech),
`FakeLectureLLM` (topics, notes, summary, quiz, grading and flashcard prompts; it can inject invalid quiz items),
and `FakeEmbedder` (bag-of-words vectors, so the embedding model is never downloaded). ChromaDB is real but
in-memory, with a new collection per test. Media tests create short tones and tiny videos with ffmpeg.

| Area | Test files (tests) | What is checked |
|---|---|---|
| Auth and security | `test_auth.py` (10) | register, login, `/me`, duplicate e-mail, wrong password, expired / invalid tokens, password byte limit |
| Errors, logging, health | `test_errors_and_logging.py` (4), `test_health.py` (5) | the error envelope for unknown routes, app errors and unhandled exceptions; request-id header and log line; health checks (degraded when the vector store fails); OpenAPI docs served; free tier is the default; production refuses the default `SECRET_KEY` |
| Configuration and providers | `test_providers.py` (9), `test_prompts_pricing.py` (5) | Groq is the default, OpenAI only when set explicitly, **no automatic paid fallback**; every prompt YAML has `id` + `version`; pricing file rules (free tier and local = $0, unknown paid model = `null`) |
| LLM client | `test_llm_client.py` (18), `test_ratelimit.py` (7) | provider routing, JSON-schema validation with one repair retry, 429 backoff on the same provider, `Retry-After`, `503 MODEL_UNAVAILABLE`, one `llm_calls` row per request; Groq tokens-per-minute pacing |
| Speech recognition and media | `test_asr_client.py` (13), `test_media.py` (9) | ffprobe duration, audio extraction, chunking under the size limit, timestamp offsets and merging, ASR retries, rejection of providers without segment times |
| Upload and pipeline | `test_lectures_api.py` (17), `test_pipeline.py` (8), `test_transcript_format.py` (4) | file type and size checks, 202 + status polling, every pipeline stage and failure path, restart recovery, delete cascades, transcript download as TXT/SRT/VTT, media endpoint with `Range` → 206 |
| Summary and notes | `test_summary_generation.py` (12), `test_summaries_api.py` (13) | single-pass vs map-reduce, segment ids converted to real times (never model times), invalid ids clamped or nulled, caching and regeneration |
| Quizzes, grading, flashcards | `test_quiz_generation.py` (36), `test_quizzes_api.py` (19), `test_grading.py` (19), `test_flashcards_api.py` (14) | question validation and regeneration rounds, answers hidden until submit, rule / LLM / embedding-fallback grading, topic mastery moving average, weak topics, Leitner boxes and due dates |
| Retrieval and chat | `test_chunking_vectorstore.py` (7), `test_rag.py` (14), `test_chat_api.py` (15), `test_calibration.py` (3) | chunk sizes and overlap, Chroma filtering by lecture, **refusal below `RAG_MIN_SCORE` with no LLM call**, model refusal, citation check, follow-up rewriting, unknown generator, Ollama unavailable → 503 |
| LLMOps and evaluation | `test_llmops_metrics.py` (12), `test_model_versions.py` (11), `test_eval.py` (19), `test_export_llmops.py` (2), `test_export_openapi.py` (2) | percentiles, cost and equivalent cost, error and parse-failure rates, refusals by layer, Ollama digests, Hit@k / MRR / context precision, judge parsing, offline import, the generated results page and OpenAPI export |
| Database and deployment | `test_migrations.py` (1), `test_docker_config.py` (8), `test_network_guard.py` (1) | Alembic upgrade creates exactly the model tables and downgrade removes them; compose file, Dockerfiles and nginx config checked offline |

**Lowest-covered application files** (from the coverage report): `db/session.py` 53 % (the Postgres engine setup,
replaced by SQLite in tests), `services/embeddings.py` 73 % (loading the real sentence-transformers model),
`main.py` 78 % (startup hooks that need a real database), `workers/pipeline.py` 83 % (rare failure branches),
`services/summaries.py` 86 %.

### Fine-tuning (`finetune/tests/`, 22 tests)

`test_data_and_metrics.py` (data preparation and the evaluation metrics: accuracy, token F1, ROUGE-L, refusal
precision/recall), `test_prompt_sync.py` (fails if the training copy of the `rag_answer@v1` prompt drifts from the
app's prompt), `test_rescore_mcq.py` (the secondary MCQ checks).

### Frontend (`frontend/src/**/*.test.*`, 60 tests in 11 files)

| File | Tests | What is checked |
|---|---|---|
| `api/client.test.ts` | 10 | Bearer token, error envelope → `ApiError` (code, message, details, Retry-After), 401 handling, downloads, multipart upload progress |
| `api/endpoints8b.test.ts` | 3 | quiz, flashcard and chat requests send the documented bodies |
| `routes.test.tsx` | 5 | login redirect, app shell, lecture tabs, 404 page |
| `pages/UploadPage.test.tsx` | 3 | file checks before upload, progress, backend error shown |
| `pages/lecture/TranscriptPage.test.tsx` | 3 | search and highlight, `?t=` deep link, media fetched only on play |
| `pages/lecture/quiz/QuizPage.test.tsx` | 2 | **quiz component**: notes required first; setup → questions → results |
| `pages/lecture/ask/AskPage.test.tsx` | 5 | **chat component**: models from `/models`, source chips, "not in lecture" badge with reason, 503 for the fine-tuned model, free-tier waiting notice, reopened session |
| `pages/lecture/flashcards/FlashcardsPage.test.tsx` | 3 | due counts and boxes, keyboard flip and re-queue, empty deck |
| `lib/lib.test.ts`, `lib/lib8b.test.ts`, `lib/llmops.test.ts` | 9 / 8 / 9 | formatting, transcript helpers, processing stepper, validation, quiz/chat helpers, dashboard stats, LLMOps chart rows and eval tables |

## 4. Manual checks (real providers)

These are run by hand, because they use the Groq free tier, the local embedding model or Ollama:

- `scripts/llm_smoke.py`, `scripts/embedding_smoke.py`: one real request each.
- `scripts/manual_phase4.*` to `manual_phase7.*`: upload → transcript → summary → quiz → flashcards → Q&A on a real recording.
- `scripts/calibrate_rag.py`: the refusal-threshold calibration ([rag.md](rag.md#3-calibrating-rag_min_score)).
- `python -m eval.run`: the golden-set evaluation ([llmops.md](llmops.md), results in [llmops_results.md](llmops_results.md)).
- Phase 12 Docker check: the full flow through `http://localhost:8080` ([deployment.md](deployment.md)).

## 5. Known gaps

- **No end-to-end browser test.** The planned Playwright smoke test was dropped from the Phase 13 scope. The full
  flow is checked by hand (§4) and in the demo.
- **No frontend coverage figure.** Vitest runs without a coverage provider, so only test counts are reported.
- **SQLite, not Postgres, in tests.** Postgres-specific behaviour (types, locking) is covered only by the manual
  runs and the Docker check. The migration test runs on SQLite too.
- **Real providers are never called in tests.** Groq, Ollama and the real embedding model are replaced by fakes, so
  prompt quality and model behaviour are measured by the evaluation harness, not by pytest.
- **CLI wrappers are untested** (`eval/run.py`, `eval/validate.py`, `eval/segments.py`, `eval/import_offline.py`,
  the smoke scripts: 0 %). The logic they call (`services/evaluation/*`) is covered at 93–100 %.
- **No continuous integration.** The tests are run locally before each commit; there is no CI pipeline in the repo.
- **Phase 9 features are not built**, so they have no tests (mind map, adaptive difficulty, recommendations).
