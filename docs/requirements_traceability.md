# Requirements traceability

Where each assignment requirement is met: the feature, the files that implement it, and the evidence a marker can
check. Requirement ids follow [IMPLEMENTATION_PLAN.md §1.1](../IMPLEMENTATION_PLAN.md#11-requirement-traceability-matrix).
Paths are relative to the repository root.

## 1. The eight assignment requirements

| # | Requirement | Where it is met (feature) | Files | Evidence |
|---|---|---|---|---|
| R1 | Two AI categories: Speech Recognition and NLP | Lecture transcription (speech); summary, notes, quiz, flashcards, grading, grounded Q&A, embeddings (NLP) | `backend/app/services/asr/`, `backend/app/services/llm/`, `backend/app/services/embeddings.py` | [ai_mapping.md](ai_mapping.md); ASR and LLM rows per task in [llmops_results.md](llmops_results.md) §3 |
| R2 | At least 5 AI subtasks, each mapped to a model | 7 subtasks (ASR, summarization, question generation, RAG question answering, text generation, embeddings, keyphrase/topic extraction) + domain fine-tuning | `backend/app/services/generation/`, `backend/app/services/rag.py`, `backend/app/prompts/*.yaml` | [ai_mapping.md](ai_mapping.md) §1; one prompt version per subtask logged in [llmops_results.md](llmops_results.md) §6 |
| R3 | Model selection with reasons | Free-tier Groq models, local bge-small, Qwen3-1.7B SLM, Ollama | `backend/app/core/config.py`, `backend/config/pricing.yaml`, `.env.example` | [model_selection.md](model_selection.md) (accuracy, cost, free tier, integration; limits hit) |
| R4 | Stack: React, FastAPI, PostgreSQL, vector DB, Docker | React 18 + Vite + TypeScript SPA; FastAPI + SQLAlchemy + Alembic; PostgreSQL 16; ChromaDB; Docker Compose | `frontend/`, `backend/app/`, `backend/alembic/`, `backend/app/services/vectorstore.py`, `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile` | `docker compose up --build` runs the whole app ([deployment.md](deployment.md)); `backend/tests/test_docker_config.py` |
| R5 | Architecture, components, data flow, API flow | System, pipeline, status, RAG and deployment diagrams | `docs/architecture.md`, `docs/images/architecture.png` | [architecture.md](architecture.md) (Mermaid diagrams §1, §3, §9, §11) |
| R6 | REST APIs with validation, errors, logging and Swagger | 39 operations; Pydantic validation; one error envelope; structlog JSON logs with request ids; Swagger at `/docs` | `backend/app/api/routers/`, `backend/app/schemas/`, `backend/app/core/errors.py`, `backend/app/core/logging.py`, `backend/app/core/middleware.py` | [api.md](api.md), [openapi.json](openapi.json); `test_errors_and_logging.py`, API tests in [testing.md](testing.md) |
| R7 | LLMOps with at least 5 measured metrics and a dashboard | 8 metrics (M1–M8) plus error, parse-failure and refusal rates; prompt and model versioning; golden-set evaluation harness; LLMOps page | `backend/app/services/llmops.py`, `backend/app/services/evaluation/`, `backend/eval/`, `backend/app/api/routers/llmops.py`, `frontend/src/pages/LlmOpsPage.tsx` | [llmops.md](llmops.md) (definitions); [llmops_results.md](llmops_results.md) (generated from the database); screenshot `docs/images/llmops.png` |
| R8 | Fine-tune an SLM on an education dataset, compare with the base model, use it in the app | Qwen3-1.7B + QLoRA on SciQ; base vs fine-tuned on 500 test items and on the lecture golden set; "Fine-tuned SLM" option on the Ask page through Ollama | `finetune/`, `backend/app/services/llm/generators.py`, `frontend/src/pages/lecture/ask/AskPage.tsx` | [finetuning.md](finetuning.md), [finetune/MODEL_CARD.md](../finetune/MODEL_CARD.md), `finetune/results/*.json`, [llmops_results.md](llmops_results.md) §8–§9 |

## 2. Supporting requirements

| # | Requirement | Where it is met | Evidence |
|---|---|---|---|
| R9 | Professional SaaS UI | Login, Register, Dashboard, Upload, Processing, Analytics, LLMOps and a 404 page, plus the lecture workspace with 6 tabs: Transcript, Summary & Notes, Quiz, Ask, Flashcards, Mind map (a placeholder; Phase 9 not built) | `frontend/src/pages/`; screenshots in `docs/images/` |
| R10 | Step-by-step development | Phases 1–8 and 10–13; Phase 9 skipped | [IMPLEMENTATION_PLAN.md §14](../IMPLEMENTATION_PLAN.md#14-progress-log); git history |
| R11 | Deliverables | Report, diagrams, demo script, contributions, test results | `docs/report/AI_Study_Buddy_Report.docx`, [demo_script.md](demo_script.md), [contributions.md](contributions.md), [testing.md](testing.md) |
| R12 | No hardcoded keys, `.env.example`, README, no invented results | All settings in `backend/app/core/config.py`; every variable in `.env.example`; numbers only from results files and the database | [.env.example](../.env.example), [README.md](../README.md), `backend/tests/test_providers.py` |
