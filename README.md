# AI Study Buddy

A web app that turns recorded lectures into transcripts, notes, quizzes, flashcards, a mind map and a grounded Q&A chat, with LLMOps metrics and a fine-tuned small language model.

- **Design and phase plan:** [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- **Rules for contributors and Claude Code:** [CLAUDE.md](CLAUDE.md)
- **Docs:** [architecture](docs/architecture.md) · [REST API](docs/api.md) · [summary & notes](docs/summarization.md) · [quizzes & flashcards](docs/quizzes.md) · [Q&A and chat](docs/rag.md)
- **Runs on free tiers by default:** Groq for speech recognition (`whisper-large-v3-turbo`) and the LLM (`openai/gpt-oss-120b`, an open-weight model hosted on Groq). OpenAI is optional and only used if you set it explicitly.

> Status: Phase 7 (grounded Q&A and chat). Ask questions about a lecture and get answers from its transcript only, with the timestamps where it is said, or a clear "not covered in the lecture". Chat supports follow-up questions. Upload a lecture recording; a background pipeline extracts the audio with ffmpeg, transcribes it with Groq Whisper, then writes a summary, key takeaways, definitions, topic-wise notes and revision notes with Groq `gpt-oss-120b`, all from the transcript only and with timestamps taken from the transcript. You can then generate validated quizzes (MCQ, true/false, short answer), get them graded with explanations and per-topic mastery, and study a flashcard deck with Leitner-box reviews. Everything runs on free tiers. The frontend is still an app shell with placeholder pages.

## Stack
FastAPI · Pydantic v2 · PostgreSQL 16 (Docker) · React 18 + Vite + TypeScript · Tailwind CSS v4 · shadcn/ui · React Router

## Local setup

### 1. Prerequisites

| Tool | Version | Windows (PowerShell) | macOS | Linux (Debian/Ubuntu) |
|---|---|---|---|---|
| Git | any recent | `winget install -e --id Git.Git` | `brew install git` | `sudo apt install git` |
| Python | 3.11+ (3.12 used) | `winget install -e --id Python.Python.3.12` | `brew install python@3.12` | `sudo apt install python3.12 python3.12-venv` |
| Node.js | 22.12+ or 24 LTS | `winget install -e --id OpenJS.NodeJS.LTS` | `brew install node@24` | [nodesource](https://github.com/nodesource/distributions) or `nvm install 24` |
| Docker | Desktop / Engine | `wsl --install` (admin, then reboot), then `winget install -e --id Docker.DockerDesktop` | `brew install --cask docker` | [Docker Engine docs](https://docs.docker.com/engine/install/) |
| ffmpeg | any recent (**required** from Phase 4) | `winget install -e --id Gyan.FFmpeg` | `brew install ffmpeg` | `sudo apt install ffmpeg` |

Open a new terminal after installing so your `PATH` is updated.

### 2. Clone and configure

```bash
git clone https://github.com/pranavshinde16/AI-study-buddy.git
cd AI-study-buddy
```

Copy the example environment file and add your free Groq key from https://console.groq.com/keys:

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `Copy-Item .env.example .env` | `cp .env.example .env` |

### 3. Start the database

```bash
docker compose up -d db
docker compose ps        # STATUS should show "healthy"
```

### 4. Backend

**Windows (PowerShell)**
```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
pytest -q
uvicorn app.main:app --reload
```

**macOS / Linux**
```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
pytest -q
uvicorn app.main:app --reload
```

`alembic upgrade head` creates or updates the database tables. Run it again after every `git pull` that adds a migration.

If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

Check: http://localhost:8000/api/health returns `{"status":"ok", ..., "checks":{"database":"ok"}}`, and http://localhost:8000/docs shows Swagger UI.

**Try auth in Swagger:** `POST /api/auth/register`, then `POST /api/auth/login`. Copy `access_token`, click **Authorize**, paste it, then call `GET /api/auth/me`.

**Try a transcription:** with the server running, upload a recording and fetch its transcript (uses your Groq free quota):

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `.\scripts\manual_phase4.ps1 -File C:\path\to\lecture.mp3` | `bash scripts/manual_phase4.sh /path/to/lecture.mp3` |

The script registers a test account, uploads the file, polls `GET /api/lectures/{id}/status` until it reaches `transcribed`, prints the first segments and saves `.txt/.srt/.vtt` files to `storage/manual-test/`. You can do the same in Swagger with `POST /api/lectures/upload`.

**Try summary & notes:** after the upload reaches `ready` (summaries are generated automatically), run:

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `.\scripts\manual_phase5.ps1 -File C:\path\to\lecture.mp3` | `bash scripts/manual_phase5.sh /path/to/lecture.mp3` |
| `.\scripts\manual_phase5.ps1 -LectureId <id> -Regenerate` | `LECTURE_ID=<id> REGENERATE=true bash scripts/manual_phase5.sh` |

It prints the summary, takeaways, definitions and topics with their timestamps, then calls `POST /api/lectures/{id}/summarize` a second time to show that the cached result returns instantly. In Swagger: `POST /api/lectures/{id}/summarize` and `GET /api/lectures/{id}/notes`. How it works: [docs/summarization.md](docs/summarization.md).

**Try quizzes & flashcards:** on a lecture that is `ready`, run:

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `.\scripts\manual_phase6.ps1` | `bash scripts/manual_phase6.sh` |
| `.\scripts\manual_phase6.ps1 -Interactive` (you type the answers) | `LECTURE_ID=<id> bash scripts/manual_phase6.sh` |

It generates a quiz on your newest `ready` lecture and prints the questions, then submits answers and shows the score, explanations, timestamps, grader and topic mastery. After that it generates the flashcard deck and reviews one card. In Swagger: `POST /api/lectures/{id}/generate-quiz`, `POST /api/quizzes/{quiz_id}/submit`, `POST /api/lectures/{id}/flashcards`, `POST /api/flashcards/{card_id}/review`. How it works: [docs/quizzes.md](docs/quizzes.md).

**Embedding model (local, free):** when the LLM grader is unavailable, short answers are graded by meaning similarity using `BAAI/bge-small-en-v1.5`. It downloads (~130 MB) and loads on first use, not at startup. To fetch it ahead of time and check it works, run `python -m scripts.embedding_smoke`. The `pip install -r requirements.txt` step now includes PyTorch (CPU), which takes a few minutes. **Linux/Docker:** run `pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu` first, to avoid ~2 GB of CUDA packages. On Windows, Hugging Face may warn that symlinks are unsupported. The warning is harmless; set `HF_HUB_DISABLE_SYMLINKS_WARNING=1` to hide it.

**Try Q&A and chat:** on a lecture that is `ready` (older lectures are indexed on their first question), run:

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `.\scripts\manual_phase7.ps1` | `bash scripts/manual_phase7.sh` |
| `.\scripts\manual_phase7.ps1 -LectureId <id> -Question "..." -FollowUp "..."` | `LECTURE_ID=<id> QUESTION="..." bash scripts/manual_phase7.sh` |

It asks an on-topic, an off-topic and a near-topic question, holds a two-turn chat with a follow-up, and tries the `finetuned` generator, which returns 503 until Ollama is set up in Phase 10. It prints each answer, its refusal reason, scores and cited timestamps. In Swagger: `POST /api/lectures/{id}/ask`, `POST /api/lectures/{id}/chat`, `GET /api/models`.

**Calibrate the refusal threshold on your lecture** (free: only the local embedding model runs, no LLM calls):

```bash
python -m scripts.calibrate_rag --lecture-id <id>      # questions: eval/calibration/demo_lecture_questions.json
```

It prints the best retrieval score of each on-topic and off-topic question and proposes `RAG_MIN_SCORE` from those scores. How it works: [docs/rag.md](docs/rag.md).

Offline speech recognition (optional): `pip install -r requirements-asr-local.txt` and set `ASR_PROVIDER=local` in `.env` (slower on CPU; the first run downloads the model).

**Check your Groq key (optional):** `python -m scripts.llm_smoke` sends one small request through the LLM client to Groq's free tier, prints the result, and logs a row in the `llm_calls` table.

### 5. Frontend (in a second terminal; same commands on every OS)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Requests to `/api/*` are proxied to the backend at `API_PROXY_TARGET` (default `http://localhost:8000`). To use a backend on another port, copy `frontend/.env.example` to `frontend/.env` and change it, or set it for one run:

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `$env:API_PROXY_TARGET="http://localhost:8001"; npm run dev` | `API_PROXY_TARGET=http://localhost:8001 npm run dev` |

Other scripts: `npm test` · `npm run typecheck` · `npm run lint` · `npm run build`

## Repository layout
See [IMPLEMENTATION_PLAN.md §11](IMPLEMENTATION_PLAN.md#11-repository-layout).
