# CLAUDE.md — AI Study Buddy

University project: a web app that turns recorded lectures into transcripts, notes, quizzes, flashcards, a mind map and a grounded Q&A chat. It also needs LLMOps metrics and a fine-tuned small language model (SLM).
**The full design and phase plan are in `IMPLEMENTATION_PLAN.md`. Read the relevant section before every phase. Only work on the phase you are asked for.**

## Stack
- Backend: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16 (psycopg 3), PyJWT + bcrypt, structlog, ChromaDB, sentence-transformers (`BAAI/bge-small-en-v1.5`), ffmpeg, OpenAI Python SDK (also used for Groq and Ollama through `base_url`)
- Frontend: React 18 + Vite + TypeScript, Tailwind, shadcn/ui, TanStack Query, React Router, Recharts, React Flow
- Fine-tuning: Unsloth + TRL + PEFT on Colab; served through Ollama (GGUF)
- Docker Compose for the full stack

## Commands
- Backend dev: `cd backend && uvicorn app.main:app --reload` (Swagger at http://localhost:8000/docs)
- Migrations: `cd backend && alembic revision --autogenerate -m "msg" && alembic upgrade head`
- Backend tests: `cd backend && pytest -q`
- Frontend dev: `cd frontend && npm run dev` · tests `npm test` · types `npm run typecheck` · lint `npm run lint`
- Database only: `docker compose up -d db` · full stack: `docker compose up --build`

## Rules you must follow
1. **Never hardcode secrets.** Every setting goes through `app/core/config.py` (pydantic-settings). Each new variable must be added to `.env.example` with a comment.
2. **Never invent results.** Don't write metrics, eval scores, fine-tuning numbers, timings or API outputs into docs or code. Numbers come only from files or database rows produced by real runs. Leave `TBD (run X)` placeholders.
3. **Grounding:** every LLM feature that works on a lecture must use only the transcript or retrieved chunks. Timestamps must come from transcript segments, never from the model. The RAG path must refuse when retrieval scores fall below `RAG_MIN_SCORE`.
4. **All model calls go through `services/llm/client.py`** (or the ASR and embedding wrappers), so every call is logged to `llm_calls` and `pipeline_runs`. No direct SDK calls anywhere else.
5. **Prompts live in `backend/app/prompts/*.yaml`** with `id` and `version`. Changing what a prompt does means bumping the version.
6. Routers contain only HTTP logic; business logic goes in `services/`. Validate inputs with Pydantic. Return the error envelope `{"error":{"code","message","details"}}`.
7. Tests must not touch the network: use fake providers or fixtures. Add or update tests with every feature.
8. Keep the frontend typed against the backend schemas. No mock data in finished pages.
9. Pin dependency versions. Explain any new dependency in one line in your summary.
10. At the end of a phase: run the tests, list the manual checks the user should run, and tick the phase in `IMPLEMENTATION_PLAN.md` §14 only after the user confirms.
11. The user is learning. Explain what each new file does, and give exact commands for Windows (PowerShell) and macOS/Linux when they differ.
12. **Free tier first.** Groq is the default for both ASR and the LLM. OpenAI is optional and is used only when `LLM_PROVIDER=openai` / `ASR_PROVIDER=openai` is set explicitly. **Never fall back to a paid provider automatically.** On Groq 429s, back off and retry; if Groq still fails or a model is unavailable, return a clear error (e.g. `503 MODEL_UNAVAILABLE` / `429 RATE_LIMITED`) instead of switching providers.
13. **Workflow:** one phase at a time, then stop and wait for the user's approval. Keep a private log per phase in `dev-log/phase-NN-<name>.md` (gitignored; check with `git check-ignore -v` and look at the staged files before every commit). Never push without explicit approval.

## Environment variables (keep `.env.example` in sync)
```
APP_ENV=development
SECRET_KEY=change-me
ACCESS_TOKEN_EXPIRE_MINUTES=1440
DATABASE_URL=postgresql+psycopg://studybuddy:studybuddy@localhost:5432/studybuddy
STORAGE_DIR=../storage
MAX_UPLOAD_MB=500
CORS_ORIGINS=http://localhost:5173
LOG_LEVEL=INFO
LOG_JSON=true

ASR_PROVIDER=groq            # groq | local | openai
ASR_MODEL=whisper-large-v3-turbo
GROQ_API_KEY=
GROQ_BASE_URL=https://api.groq.com/openai/v1
OPENAI_API_KEY=              # optional, paid; only used if a provider is explicitly set to openai

LLM_PROVIDER=groq            # groq (free tier, default) | openai (paid, opt-in)
LLM_MODEL=openai/gpt-oss-120b   # open-weight model hosted on Groq (free tier); not the OpenAI API
JUDGE_MODEL=openai/gpt-oss-120b
LLM_MAX_RETRIES=3            # same provider only, never a paid fallback
LLM_BACKOFF_BASE_SEC=2.0
LLM_BACKOFF_MAX_SEC=30.0
LLM_TIMEOUT_SEC=120
LLM_MAX_OUTPUT_TOKENS=4096

EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
CHROMA_DIR=../storage/chroma
RAG_TOP_K=5
RAG_MIN_SCORE=0.35

FINETUNED_BASE_URL=http://localhost:11434/v1
FINETUNED_MODEL_TAG=study-buddy-qwen
BASE_SLM_MODEL_TAG=qwen3:1.7b
```
