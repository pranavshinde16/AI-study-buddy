# Backend image: FastAPI + ffmpeg + CPU-only torch (Phase 12).
# Build context is backend/ (see docker-compose.yml). Runs as a non-root user.

FROM python:3.12.16-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Hugging Face cache for the embedding model (a named volume, so it downloads only once)
    HF_HOME=/data/hf-cache

# ffmpeg/ffprobe: audio extraction and chunking for speech-to-text
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU build of torch first (the default PyPI wheel pulls ~2 GB of CUDA libraries).
# 2.14.1+cpu satisfies `torch==2.14.1` in requirements.txt, so pip keeps it.
RUN pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# Non-root user; the data folders are created here so new named volumes inherit this owner.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/storage /data/chroma /data/hf-cache \
    && chown -R app:app /data

COPY --chown=app:app . .
RUN chmod +x docker/entrypoint.sh docker/seed-volumes.sh

USER app
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["docker/entrypoint.sh"]
