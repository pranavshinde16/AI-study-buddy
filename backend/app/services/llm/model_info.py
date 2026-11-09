"""Model version details for LLMOps (Phase 11): what exactly answered a request.

- Groq / OpenAI: the model string the provider returns in each response (already in ChatResult).
- Ollama: its OpenAI-compatible /v1 API echoes only the tag ("study-buddy-qwen"), which says
  nothing about WHICH build of that tag ran. The native API (`GET /api/tags`) lists each local
  model's digest, so `llm_calls.model_version` becomes "study-buddy-qwen@sha256:<digest>".
  The list is cached for TAGS_TTL_SEC; a failed lookup never breaks a request (version = tag).
- Embeddings: the Hugging Face commit of the locally cached model (see embeddings.py).

This module only reads metadata; it never sends a prompt to a model (CLAUDE.md rule 4).
"""

import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

TAGS_TTL_SEC = 300.0  # re-read after this, so `ollama create` of a new build is picked up
FAILED_TTL_SEC = 30.0  # after a failed lookup, don't retry (and wait on a refused port) for this long
TIMEOUT_SEC = 2.0


@dataclass(frozen=True)
class OllamaModel:
    name: str  # e.g. "study-buddy-qwen:latest"
    digest: str | None
    size_bytes: int | None
    modified_at: str | None
    details: dict[str, Any]


def native_root(base_url: str) -> str:
    """http://localhost:11434/v1 -> http://127.0.0.1:11434 (the native Ollama API root).

    "localhost" becomes 127.0.0.1: on Windows, localhost is tried as IPv6 (::1) first, and
    Ollama listens on IPv4 only, which cost ~2 s per lookup in the live check."""
    root = base_url.rstrip("/")
    root = root[: -len("/v1")] if root.endswith("/v1") else root
    return root.replace("://localhost:", "://127.0.0.1:").replace("://localhost/", "://127.0.0.1/")


def _with_tag(name: str) -> str:
    return name if ":" in name else f"{name}:latest"


class OllamaModelInfo:
    def __init__(self, base_url: str, fetch=None, clock=time.monotonic) -> None:
        self.root = native_root(base_url)
        self._fetch = fetch or self._http_fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._models: dict[str, OllamaModel] | None = None
        self._expires = 0.0

    def _http_fetch(self) -> dict[str, Any]:
        resp = httpx.get(f"{self.root}/api/tags", timeout=TIMEOUT_SEC)
        resp.raise_for_status()
        return resp.json()

    def models(self) -> dict[str, OllamaModel] | None:
        """name -> model, or None if Ollama could not be reached (cached either way)."""
        with self._lock:
            now = self._clock()
            if now < self._expires:
                return self._models
            try:
                raw = self._fetch()
                self._models = {
                    m["name"]: OllamaModel(
                        name=m["name"], digest=m.get("digest"), size_bytes=m.get("size"),
                        modified_at=m.get("modified_at"), details=m.get("details") or {},
                    )
                    for m in raw.get("models", []) if m.get("name")
                }
                self._expires = now + TAGS_TTL_SEC
            except Exception as exc:  # noqa: BLE001 - metadata only; never break a request
                log.info("ollama_tags_unavailable", root=self.root, error_type=type(exc).__name__)
                self._models = None
                self._expires = now + FAILED_TTL_SEC
            return self._models

    def get(self, tag: str) -> OllamaModel | None:
        models = self.models()
        if not models:
            return None
        return models.get(tag) or models.get(_with_tag(tag))

    def version(self, tag: str, reported: str | None) -> str | None:
        """The value for llm_calls.model_version: "<reported or tag>@sha256:<digest>"."""
        m = self.get(tag)
        name = reported or tag
        if m is None or not m.digest:
            return name
        digest = m.digest.removeprefix("sha256:")
        return f"{name}@sha256:{digest}"


class ModelVersionResolver:
    """Turns the provider-reported model string into the stored model_version."""

    def __init__(self, ollama: OllamaModelInfo | None = None) -> None:
        self.ollama = ollama

    def __call__(self, provider: str, model: str, reported: str | None) -> str | None:
        if provider == "ollama" and self.ollama is not None:
            return self.ollama.version(model, reported)
        return reported


_ollama_info: dict[str, OllamaModelInfo] = {}
_ollama_lock = threading.Lock()


def get_ollama_info(base_url: str) -> OllamaModelInfo:
    """One cached instance per Ollama URL (shared by the LLM client and the model registry)."""
    with _ollama_lock:
        if base_url not in _ollama_info:
            _ollama_info[base_url] = OllamaModelInfo(base_url)
        return _ollama_info[base_url]
