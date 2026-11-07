"""Application settings, loaded from environment variables and the repo-root `.env` file.

Every configurable value lives here (CLAUDE.md rule 1). Add new variables to `.env.example` too.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[2] is backend/, parents[3] is the repository root
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

ProviderName = Literal["groq", "openai", "ollama"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore vars meant for other services (e.g. POSTGRES_*)
    )

    # --- App ---
    app_name: str = "AI Study Buddy"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 1440
    database_url: str = "postgresql+psycopg://studybuddy:studybuddy@localhost:5432/studybuddy"
    storage_dir: str = "../storage"
    max_upload_mb: int = 500
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    log_json: bool = True

    # --- Speech recognition (free Groq tier by default) ---
    asr_provider: Literal["groq", "local", "openai"] = "groq"
    asr_model: str = "whisper-large-v3-turbo"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    openai_api_key: str = ""  # optional, paid; never used unless a provider is explicitly "openai"
    openai_asr_model: str = "whisper-1"  # only whisper-1 returns segment timestamps on OpenAI
    asr_language: str = ""  # ISO-639-1 code such as "en"; blank = let Whisper detect it
    asr_chunk_sec: int = 600  # audio is cut into pieces of this length before transcription
    asr_max_chunk_mb: float = 24.0  # Groq free tier accepts files up to 25 MB
    local_asr_model: str = "small"  # faster-whisper model name (ASR_PROVIDER=local only)
    local_asr_device: str = "cpu"  # cpu | cuda
    local_asr_compute_type: str = "int8"  # int8 is fastest on CPU
    ffmpeg_bin: str = "ffmpeg"  # path or name of the ffmpeg executable
    ffprobe_bin: str = "ffprobe"
    media_timeout_sec: int = 1800  # max time for one ffmpeg/ffprobe run

    # --- LLM (free Groq tier by default; OpenAI is opt-in only, never a fallback) ---
    llm_provider: Literal["groq", "openai"] = "groq"
    llm_model: str = "openai/gpt-oss-120b"
    judge_model: str = "openai/gpt-oss-120b"
    llm_max_retries: int = 3  # retries on 429 / transient errors, same provider only
    llm_backoff_base_sec: float = 2.0  # exponential backoff: base * 2**attempt (or Retry-After)
    llm_backoff_max_sec: float = 30.0
    llm_timeout_sec: float = 120.0
    llm_max_output_tokens: int = 4096
    llm_reasoning_effort: str = "low"  # low | medium | high | "" (provider default); sent to groq/openai only
    groq_tokens_per_minute: int = 8000  # client-side pacing for Groq's free-tier TPM limit; 0 = off

    # --- Summary & notes (Phase 5) ---
    summary_auto: bool = True  # generate summary + topic notes automatically after transcription
    summary_single_pass_max_tokens: int = 3500  # longer transcripts are processed in windows (map-reduce)
    summary_window_sec: int = 600  # target window length for map-reduce (~10 min)
    summary_window_max_tokens: int = 2500  # hard cap per window so one request fits the free-tier TPM

    # --- Retrieval ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    chroma_dir: str = "../storage/chroma"
    rag_top_k: int = 5
    rag_min_score: float = 0.35

    # --- SLM via Ollama ---
    finetuned_base_url: str = "http://localhost:11434/v1"
    finetuned_model_tag: str = "study-buddy-qwen"
    base_slm_model_tag: str = "qwen3:1.7b"

    @model_validator(mode="after")
    def _no_default_secret_in_production(self) -> "Settings":
        if self.app_env == "production" and (self.secret_key == "change-me" or len(self.secret_key) < 32):
            raise ValueError("SECRET_KEY must be a random value of at least 32 characters when APP_ENV=production")
        return self

    @property
    def storage_path(self) -> Path:
        """STORAGE_DIR as an absolute path; a relative value is resolved against backend/."""
        p = Path(self.storage_dir)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS is a comma-separated string in .env; split it into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance; use as a FastAPI dependency so tests can override it."""
    return Settings()
