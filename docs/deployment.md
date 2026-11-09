# Docker and deployment (Phase 12)

How to run the whole app with Docker Compose on your own computer, and how to put it on a small Linux server.

## 1. What runs

| Service | Image | What it does | Data |
|---|---|---|---|
| `db` | `postgres:16` | Database | volume `pgdata` |
| `backend` | built from `backend/Dockerfile` | FastAPI + ffmpeg + the embedding model (CPU). On start it runs `alembic upgrade head`, then uvicorn | volumes `storage` (uploads, audio), `chroma` (vectors), `hf-cache` (embedding model download); `finetune/results` mounted read-only |
| `frontend` | built from `frontend/Dockerfile` | nginx serving the built React app; forwards `/api`, `/docs`, `/openapi.json` to the backend | none |
| `ollama` *(optional, `--profile ollama`)* | `ollama/ollama:0.40.15` | Runs the local models in a container | volume `ollama` |
| `seed` *(one-off, `--profile seed`)* | the backend image | Copies `./storage` into the `storage` and `chroma` volumes once | none |

Start order: `db` healthy → `backend` healthy (`GET /api/health`) → `frontend`. Only the frontend is published
(`http://localhost:8080`, change with `FRONTEND_PORT`); the backend is reachable only through nginx. The database
port 5432 stays published for local development.

Settings come from the repo-root `.env`, exactly as in development. Inside the containers, compose overrides only the
values that must differ: `DATABASE_URL` (host `db`), `STORAGE_DIR`, `CHROMA_DIR`, `HF_HOME`, `FINETUNE_RESULTS_DIR`
and `FINETUNED_BASE_URL`.

## 2. Run it on your computer

Same commands in PowerShell, macOS and Linux (run them in the repo root):

```
docker compose up --build -d      # build the images and start everything (first build takes several minutes)
docker compose ps                 # all services should become "healthy"
```

Open **http://localhost:8080**. Swagger is at http://localhost:8080/docs.

| Task | Command |
|---|---|
| Follow the backend logs | `docker compose logs -f backend` |
| Stop (keep data) | `docker compose down` |
| Rebuild after code changes | `docker compose up --build -d` |
| Run the backend tests in the image | `docker compose exec backend pytest -q` |
| Delete **all** data (database, uploads, vectors) | `docker compose down -v` (cannot be undone) |

**First run with existing lectures.** If you already used the app in development, your files are in `./storage`
while the lecture rows are in the database. Copy the files into the volumes once (stop `uvicorn` first so the vector
store is not being written):

```
docker compose build backend
docker compose --profile seed run --rm seed
```

It refuses to copy into volumes that already contain data. To copy over them anyway: `SEED_FORCE=1` in front of the
command (macOS/Linux) or `$env:SEED_FORCE="1";` before it (PowerShell). After that, development (`./storage`) and
Docker (the volumes) keep separate copies.

The embedding model (`BAAI/bge-small-en-v1.5`) downloads into the `hf-cache` volume the first time it is needed and
is reused afterwards.

## 3. The local models (Ollama)

**Default: Ollama on your computer.** The backend container calls `http://host.docker.internal:11434/v1`, so the
models you created in Phase 10 (`study-buddy-qwen`, `study-buddy-qwen-base`) work without copying anything. Docker
Desktop (Windows, macOS) provides `host.docker.internal`; compose adds it on Linux too. On a **Linux** host, Ollama
must listen on an address the containers can reach: by default it listens only on `127.0.0.1`, so set
`OLLAMA_HOST=0.0.0.0` for the Ollama service and block port 11434 in the firewall.

**Optional: Ollama in a container.** Useful on a server.

```
# 1. In .env:  DOCKER_FINETUNED_BASE_URL=http://ollama:11434/v1
docker compose --profile ollama up -d
# 2. Load the GGUF files from finetune/ (mounted read-only at /finetune):
docker compose exec ollama ollama create study-buddy-qwen -f /finetune/Modelfile
docker compose exec ollama ollama create study-buddy-qwen-base -f /finetune/Modelfile.base
docker compose exec ollama ollama list
```

The GGUF files are not in git (`*.gguf` is ignored); copy them into `finetune/` first. A model that is not loaded
gives a clear `503 MODEL_UNAVAILABLE` for that generator; the cloud generator keeps working. Remove the setting from
`.env` to go back to the Ollama on your computer.

> **Git Bash on Windows** rewrites arguments that start with `/` (e.g. `/finetune/Modelfile`) into Windows paths.
> Use PowerShell, or run `export MSYS_NO_PATHCONV=1` first.

## 4. Deploy to a small Linux VM

One VM runs the same `docker-compose.yml`. Any provider works (an always-free cloud VM or a low-cost VPS); check the
provider's current prices and free-tier limits yourself, they change.

**Size.** Measured on the development machine (2026-11-09, `docker stats`) after transcribing a lecture and
answering questions: backend 518 MiB, database 56 MiB, frontend 18 MiB. The backend image is about 3.2 GB on disk
(torch CPU, ffmpeg, Python packages). Running Ollama on the same VM adds the models: each GGUF file is about 1.1 GB,
and a loaded model needs at least that much RAM; on CPU, answers took 16–31 s per question in Phase 11 (p50 to p95).
So the measured total without Ollama is about 0.6 GiB: leave headroom for the operating system and for peaks while a
lecture is being processed, and add the model sizes if Ollama runs on the same VM. Disk: the images, uploads and models.

**Steps** (Ubuntu/Debian):

```bash
# 1. Docker Engine + compose plugin: https://docs.docker.com/engine/install/  then:
sudo usermod -aG docker $USER && newgrp docker

# 2. Code and settings
git clone https://github.com/pranavshinde16/AI-study-buddy.git && cd AI-study-buddy
cp .env.example .env
nano .env        # GROQ_API_KEY, APP_ENV=production, SECRET_KEY, POSTGRES_PASSWORD (see below)

# 3. Start
docker compose up --build -d
docker compose ps
```

Settings to change in `.env` on a server:

| Setting | Why |
|---|---|
| `APP_ENV=production` | The app refuses to start in production with the default `SECRET_KEY` |
| `SECRET_KEY` | A random value of at least 32 characters: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `POSTGRES_PASSWORD` | Not the default `studybuddy` (compose builds `DATABASE_URL` from it) |
| `FRONTEND_PORT` | `8080` behind a reverse proxy (below), or `80` without one |

Also delete the `ports:` lines of the `db` service in `docker-compose.yml` on a public server, so Postgres is not
reachable from the internet.

**HTTPS.** Put a reverse proxy in front of port 8080. With [Caddy](https://caddyserver.com/docs/install) installed
on the VM and a domain pointing at it, `/etc/caddy/Caddyfile` needs only:

```
studybuddy.example.com {
    reverse_proxy localhost:8080
    request_body {
        max_size 500MB
    }
}
```

Caddy obtains and renews the certificate. Open only ports 80 and 443 in the firewall.

**Updating:** `git pull && docker compose up --build -d` (migrations run on start).
**Backups:** `docker compose exec db pg_dump -U studybuddy studybuddy > backup.sql`, plus the `storage` volume
(e.g. `docker run --rm -v ai-study-buddy_storage:/data -v "$PWD":/backup alpine tar czf /backup/storage.tgz -C /data .`).
The `chroma` volume can be rebuilt: a lecture whose vectors are missing is re-indexed on its first question.

`APP_ENV` is part of the vector collection name (`lecture_chunks_<APP_ENV>`), so changing it on an existing install
makes each lecture re-index once, on its first question.

## 5. Trade-offs

The Render column describes its free web services as documented when this guide was written; check Render's current
documentation before deciding.

| | Small Linux VM (this guide) | Render (managed platform) |
|---|---|---|
| Setup | You install Docker, set up HTTPS (Caddy) and apply OS updates | Deploys from GitHub; HTTPS included |
| Same as local | Yes: the same `docker-compose.yml` | No: each service is configured separately (web service, static site, managed Postgres) |
| Persistent files | The VM's disk (volumes) | Free web services have no persistent disk; uploads and vectors would need a paid disk or object storage |
| Memory | Whatever the VM has | Free instances have little memory for torch + the embedding model (backend measured at 518 MiB above) |
| Local models | Ollama can run on the VM (CPU, slow) | No Ollama: only the cloud generator; `finetuned`/`base` return `503 MODEL_UNAVAILABLE` |
| Idle behaviour | Always on | Free web services sleep when idle; the first request after that is slow, and a lecture being processed in the background can be interrupted |
| Background processing | In-process tasks run as long as the container runs | Needs an always-on instance for long transcriptions |

For this project the VM is the better fit: the app keeps uploads and vectors on disk, loads an embedding model into
memory, and the fine-tuned model needs Ollama. Render suits a demo of the cloud generator only, with paid add-ons for
storage.
