# AI Study Buddy

A web app that turns recorded lectures into transcripts, notes, quizzes, flashcards, a mind map and a grounded Q&A chat, with LLMOps metrics and a fine-tuned small language model.

- **Design and phase plan:** [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- **Rules for contributors and Claude Code:** [CLAUDE.md](CLAUDE.md)
- **Runs on free tiers by default:** Groq for speech recognition (`whisper-large-v3-turbo`) and the LLM (`openai/gpt-oss-120b`, an open-weight model hosted on Groq). OpenAI is optional and only used if you set it explicitly.

> Status: Phase 2 (scaffold). The backend exposes `/api/health`; the frontend is an app shell with placeholder pages.

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
| ffmpeg | any recent (needed from Phase 4) | `winget install -e --id Gyan.FFmpeg` | `brew install ffmpeg` | `sudo apt install ffmpeg` |

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
pytest -q
uvicorn app.main:app --reload
```

**macOS / Linux**
```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```

If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

Check: http://localhost:8000/api/health returns `{"status":"ok",...}`, and http://localhost:8000/docs shows Swagger UI.

### 5. Frontend (in a second terminal; same commands on every OS)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Requests to `/api/*` are proxied to the backend on port 8000.

Other scripts: `npm test` · `npm run typecheck` · `npm run lint` · `npm run build`

## Repository layout
See [IMPLEMENTATION_PLAN.md §11](IMPLEMENTATION_PLAN.md#11-repository-layout).
