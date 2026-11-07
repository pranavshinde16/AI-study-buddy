"""Speech-recognition adapters (IMPLEMENTATION_PLAN §5.2), chosen by ASR_PROVIDER:

    groq    Groq-hosted Whisper (free tier, default) via the OpenAI SDK with GROQ_BASE_URL
    openai  OpenAI whisper-1 (paid, opt-in only)
    local   faster-whisper on your own CPU/GPU (free, offline; optional install)

Only `services/asr/client.py` uses these (CLAUDE.md rule 4). Adapters never retry and never
fall back to another provider: they raise `ProviderError` and the client decides.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import openai

from app.core.config import Settings
from app.services.llm.errors import ProviderNotConfiguredError
from app.services.llm.providers import ProviderError, to_provider_error


@dataclass
class ASRSegment:
    start: float  # seconds from the start of THIS audio file
    end: float
    text: str


@dataclass
class ASRResult:
    segments: list[ASRSegment]
    language: str | None = None
    duration_sec: float | None = None
    model_version: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class ASRProvider(Protocol):
    name: str

    def transcribe(self, path: Path, *, model: str, language: str | None) -> ASRResult: ...


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def parse_verbose_json(resp: Any) -> ASRResult:
    """Map a Whisper `verbose_json` response (SDK object or dict) to an ASRResult."""
    segments = [
        ASRSegment(start=float(_get(s, "start", 0.0)), end=float(_get(s, "end", 0.0)), text=str(_get(s, "text", "")).strip())
        for s in (_get(resp, "segments") or [])
    ]
    duration = _get(resp, "duration")
    return ASRResult(
        segments=segments,
        language=_get(resp, "language"),
        duration_sec=float(duration) if duration is not None else None,
    )


class OpenAICompatibleWhisper:
    """Groq and OpenAI expose the same /audio/transcriptions endpoint."""

    def __init__(self, name: str, *, base_url: str | None, api_key: str, timeout: float) -> None:
        self.name = name
        # max_retries=0: the ASR client owns retries so every attempt is logged.
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)

    def transcribe(self, path: Path, *, model: str, language: str | None) -> ASRResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "response_format": "verbose_json",
            "timestamp_granularities": ["segment"],
            "temperature": 0.0,
        }
        if language:
            kwargs["language"] = language
        try:
            with path.open("rb") as f:
                resp = self._client.audio.transcriptions.create(file=(path.name, f), **kwargs)
        except openai.OpenAIError as exc:
            raise to_provider_error(exc) from exc
        result = parse_verbose_json(resp)
        if not result.segments and str(_get(resp, "text", "")).strip():
            # Text without segments means the model can't give timestamps; we never invent them (rule 3).
            raise ProviderError(
                "bad_request",
                f"Model '{model}' returned no segment timestamps. Use a Whisper model that supports verbose_json.",
                error_type="NoSegments",
            )
        return result


class LocalFasterWhisper:
    """Runs faster-whisper locally. Install with: pip install -r requirements-asr-local.txt"""

    name = "local"

    def __init__(self, *, device: str, compute_type: str) -> None:
        self.device = device
        self.compute_type = compute_type
        self._models: dict[str, Any] = {}

    def _model(self, model: str) -> Any:
        if model not in self._models:
            try:
                from faster_whisper import WhisperModel  # optional dependency
            except ImportError as exc:
                raise ProviderNotConfiguredError(
                    "ASR_PROVIDER=local needs faster-whisper. Install it with "
                    "`pip install -r requirements-asr-local.txt`, or use ASR_PROVIDER=groq (free).",
                    details={"provider": "local"},
                ) from exc
            # The first run downloads the model from Hugging Face.
            self._models[model] = WhisperModel(model, device=self.device, compute_type=self.compute_type)
        return self._models[model]

    def transcribe(self, path: Path, *, model: str, language: str | None) -> ASRResult:
        whisper = self._model(model)
        try:
            segments, info = whisper.transcribe(str(path), language=language or None, beam_size=5)
            segs = [ASRSegment(float(s.start), float(s.end), s.text.strip()) for s in segments]
        except Exception as exc:  # noqa: BLE001 - local inference errors are not retryable
            raise ProviderError("error", str(exc), error_type=type(exc).__name__) from exc
        return ASRResult(segments=segs, language=info.language, duration_sec=info.duration, model_version=f"faster-whisper/{model}")


def build_asr_provider(name: str, settings: Settings) -> ASRProvider:
    """Create the adapter for an explicitly chosen ASR provider. Never substitutes another one."""
    if name == "groq":
        if not settings.groq_api_key:
            raise ProviderNotConfiguredError(
                "GROQ_API_KEY is not set. Add your free key from https://console.groq.com/keys to .env",
                details={"provider": "groq"},
            )
        return OpenAICompatibleWhisper(
            "groq", base_url=settings.groq_base_url, api_key=settings.groq_api_key, timeout=settings.llm_timeout_sec
        )
    if name == "openai":
        if not settings.openai_api_key:
            raise ProviderNotConfiguredError(
                "OpenAI is optional and not configured (OPENAI_API_KEY is empty). "
                "Use ASR_PROVIDER=groq for the free tier.",
                details={"provider": "openai"},
            )
        return OpenAICompatibleWhisper(
            "openai", base_url=None, api_key=settings.openai_api_key, timeout=settings.llm_timeout_sec
        )
    if name == "local":
        return LocalFasterWhisper(device=settings.local_asr_device, compute_type=settings.local_asr_compute_type)
    raise ProviderNotConfiguredError(f"Unknown ASR provider '{name}'", details={"provider": name})


def model_for(name: str, settings: Settings) -> str:
    """The model name each provider expects."""
    if name == "openai":
        return settings.openai_asr_model
    if name == "local":
        return settings.local_asr_model
    return settings.asr_model
