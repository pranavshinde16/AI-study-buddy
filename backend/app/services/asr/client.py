"""The single entry point for speech recognition (CLAUDE.md rule 4).

    asr = get_asr_client()
    result = asr.transcribe_chunk(chunk_path, audio_sec=600.0, lecture_id=..., user_id=...)

- Provider = ASR_PROVIDER (groq by default). It NEVER switches provider on failure (CLAUDE.md 12).
- 429 / outages: retried on the SAME provider with the shared backoff (Retry-After honoured).
- Every request sent writes one `llm_calls` row with task="asr" (latency, status, cost from
  the real audio length and config/pricing.yaml).
"""

import hashlib
import time
import uuid
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import structlog
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models.llmops import LLMCall
from app.services.asr.providers import ASRProvider, ASRResult, build_asr_provider, model_for
from app.services.llm.errors import (
    LLMError,
    ModelUnavailableError,
    ProviderNotConfiguredError,
    RateLimitedError,
)
from app.services.llm.calllog import save_call
from app.services.llm.pricing import PricingTable
from app.services.llm.providers import ProviderError
from app.services.llm.retry import backoff_delay

log = structlog.get_logger(__name__)

TASK = "asr"


class ASRClient:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session] | Callable[[], Session],
        pricing: PricingTable,
        providers: dict[str, ASRProvider] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self._session_factory = session_factory
        self.pricing = pricing
        self._providers: dict[str, ASRProvider] = dict(providers or {})
        self._sleep = sleep

    @property
    def provider_name(self) -> str:
        return self.settings.asr_provider

    @property
    def model(self) -> str:
        return model_for(self.provider_name, self.settings)

    def _get_provider(self, name: str) -> ASRProvider:
        if name not in self._providers:
            self._providers[name] = build_asr_provider(name, self.settings)
        return self._providers[name]

    def transcribe_chunk(
        self,
        path: Path,
        *,
        audio_sec: float | None,
        lecture_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
    ) -> ASRResult:
        name, model = self.provider_name, self.model
        language = self.settings.asr_language or None
        request_hash = hashlib.sha256(f"{name}|{model}|{path.name}|{audio_sec}".encode()).hexdigest()
        log_kw = dict(provider=name, model=model, lecture_id=lecture_id, user_id=user_id, request_hash=request_hash)

        try:
            provider = self._get_provider(name)
        except ProviderNotConfiguredError as exc:
            self._log(**log_kw, attempt=1, status="not_configured", error=exc)
            raise

        retries = self.settings.llm_max_retries
        for retry_index in range(retries + 1):
            attempt = retry_index + 1
            start = time.perf_counter()
            try:
                result = provider.transcribe(path, model=model, language=language)
            except ProviderNotConfiguredError as exc:  # e.g. faster-whisper not installed
                self._log(**log_kw, attempt=attempt, status="not_configured", error=exc)
                raise
            except ProviderError as exc:
                latency = (time.perf_counter() - start) * 1000
                status = "rate_limited" if exc.kind == "rate_limited" else "unavailable" if exc.retryable else "error"
                self._log(**log_kw, attempt=attempt, status=status, error=exc, latency_ms=latency)
                if exc.retryable and retry_index < retries:
                    delay = backoff_delay(self.settings, retry_index, exc.retry_after)
                    log.warning("asr_retry", provider=name, model=model, kind=exc.kind, retry_in_sec=delay,
                                retry=attempt, max_retries=retries)
                    self._sleep(delay)
                    continue
                raise self._to_app_error(exc, name, model) from exc

            latency = (time.perf_counter() - start) * 1000
            seconds = result.duration_sec if result.duration_sec is not None else audio_sec
            cost = self.pricing.audio_cost(name, model, seconds)
            self._log(**log_kw, attempt=attempt, status="ok", latency_ms=latency, cost_usd=cost,
                      model_version=result.model_version)
            return result
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _to_app_error(exc: ProviderError, provider: str, model: str) -> LLMError:
        details = {"provider": provider, "model": model, "task": TASK}
        if exc.kind == "rate_limited":
            return RateLimitedError(
                f"{provider} speech-recognition rate limit reached. Wait a few minutes and try again "
                "(free-tier limits apply; no paid fallback is used).",
                retry_after=exc.retry_after,
                details=details,
            )
        if exc.kind == "model_not_found":
            return ModelUnavailableError(
                f"ASR model '{model}' is not available on {provider}. Check ASR_MODEL in .env.", details=details
            )
        if exc.kind == "unavailable":
            return ModelUnavailableError(f"{provider} speech recognition is unreachable. Try again shortly.",
                                         details=details)
        if exc.kind == "auth":
            return ProviderNotConfiguredError(f"{provider} rejected the API key. Check it in .env.", details=details)
        return LLMError(f"{provider} transcription failed: {exc.message[:300]}", details=details)

    def _log(
        self,
        *,
        provider: str,
        model: str,
        lecture_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        request_hash: str,
        attempt: int,
        status: str,
        latency_ms: float | None = None,
        cost_usd: float | None = None,
        model_version: str | None = None,
        error: Exception | None = None,
    ) -> None:
        row = LLMCall(
            user_id=user_id,
            lecture_id=lecture_id,
            task=TASK,
            provider=provider,
            model=model,
            model_version=model_version,
            attempt=attempt,
            latency_ms=round(latency_ms, 2) if latency_ms is not None else None,
            cost_usd=cost_usd,
            status=status,
            error_type=(getattr(error, "error_type", None) or type(error).__name__) if error else None,
            error_message=(getattr(error, "message", None) or str(error))[:2000] if error else None,
            request_hash=request_hash,
        )
        log.info("asr_call", provider=provider, model=model, attempt=attempt, status=status,
                 latency_ms=row.latency_ms, cost_usd=cost_usd)
        save_call(self._session_factory, row)


@lru_cache
def get_asr_client() -> ASRClient:
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.services.llm.pricing import get_pricing

    return ASRClient(get_settings(), get_session_factory(), get_pricing())
