"""Application settings, loaded from environment variables and the repo-root `.env` file.

Every configurable value lives here (CLAUDE.md rule 1). Add new variables to `.env.example` too.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] is the repository root
REPO_ROOT = Path(__file__).resolve().parents[3]


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

    # --- Speech recognition (free Groq tier by default) ---
    asr_provider: Literal["groq", "local", "openai"] = "groq"
    asr_model: str = "whisper-large-v3-turbo"
    groq_api_key: str = ""
    openai_api_key: str = ""  # optional, paid; never used unless a provider is explicitly "openai"

    # --- LLM (free Groq tier by default; OpenAI is opt-in only, never a fallback) ---
    llm_provider: Literal["groq", "openai"] = "groq"
    llm_model: str = "openai/gpt-oss-120b"
    judge_model: str = "openai/gpt-oss-120b"

    # --- Retrieval ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    chroma_dir: str = "../storage/chroma"
    rag_top_k: int = 5
    rag_min_score: float = 0.35

    # --- SLM via Ollama ---
    finetuned_base_url: str = "http://localhost:11434/v1"
    finetuned_model_tag: str = "study-buddy-qwen"
    base_slm_model_tag: str = "qwen3:1.7b"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS is a comma-separated string in .env; split it into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance; use as a FastAPI dependency so tests can override it."""
    return Settings()
