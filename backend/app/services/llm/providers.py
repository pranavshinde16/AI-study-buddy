"""Provider adapters. Every provider speaks the OpenAI chat-completions API, so one adapter
(the OpenAI SDK with a different `base_url`) covers Groq, OpenAI and Ollama.

Only `client.py` uses these (CLAUDE.md rule 4). Adapters never retry and never fall back:
they translate SDK errors into `ProviderError` and the client decides what to do.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

import openai

from app.core.config import Settings
from app.services.llm.errors import ProviderNotConfiguredError

ErrorKind = Literal["rate_limited", "unavailable", "model_not_found", "auth", "bad_request", "error"]
RETRYABLE: frozenset[str] = frozenset({"rate_limited", "unavailable"})


@dataclass
class ChatResult:
    text: str
    model_version: str | None  # model string reported by the provider
    input_tokens: int | None
    output_tokens: int | None


class ProviderError(Exception):
    def __init__(
        self,
        kind: ErrorKind,
        message: str,
        *,
        error_type: str,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.error_type = error_type
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE


class ChatProvider(Protocol):
    name: str

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool,
        max_output_tokens: int,
        temperature: float | None,
        reasoning_effort: str | None = None,
    ) -> ChatResult: ...


def _retry_after(exc: openai.APIStatusError) -> float | None:
    try:
        value = exc.response.headers.get("retry-after")
        return float(value) if value is not None else None
    except (AttributeError, ValueError):
        return None


def to_provider_error(exc: Exception) -> ProviderError:
    """Translate an OpenAI-SDK exception (from any OpenAI-compatible provider) into a ProviderError."""
    if isinstance(exc, openai.RateLimitError):
        return ProviderError("rate_limited", str(exc), error_type="RateLimitError", retry_after=_retry_after(exc))
    if isinstance(exc, openai.NotFoundError):
        return ProviderError("model_not_found", str(exc), error_type="NotFoundError")
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ProviderError("auth", str(exc), error_type=type(exc).__name__)
    if isinstance(exc, (openai.BadRequestError, openai.UnprocessableEntityError)):
        # Groq reports decommissioned models as 400 "model_decommissioned".
        kind: ErrorKind = "model_not_found" if "decommission" in str(exc).lower() else "bad_request"
        return ProviderError(kind, str(exc), error_type=type(exc).__name__)
    if isinstance(exc, openai.InternalServerError):
        return ProviderError("unavailable", str(exc), error_type="InternalServerError")
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return ProviderError("unavailable", str(exc), error_type=type(exc).__name__)
    if isinstance(exc, openai.APIStatusError):
        kind = "unavailable" if exc.status_code >= 500 else "error"
        return ProviderError(kind, str(exc), error_type="APIStatusError")
    return ProviderError("error", str(exc), error_type=type(exc).__name__)


class OpenAICompatibleProvider:
    def __init__(self, name: str, *, base_url: str | None, api_key: str, timeout: float) -> None:
        self.name = name
        # max_retries=0: the LLM client owns retries so every attempt is logged to llm_calls.
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool,
        max_output_tokens: int,
        temperature: float | None,
        reasoning_effort: str | None = None,
    ) -> ChatResult:
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_completion_tokens": max_output_tokens}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if reasoning_effort:
            # gpt-oss / gpt-5 reasoning models: "low" keeps the hidden reasoning tokens (which count
            # towards Groq's tokens-per-minute limit) small.
            kwargs["reasoning_effort"] = reasoning_effort

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as exc:
            raise to_provider_error(exc) from exc

        choice = resp.choices[0] if resp.choices else None
        text = (choice.message.content or "") if choice else ""
        usage = resp.usage
        return ChatResult(
            text=text,
            model_version=resp.model,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )


def build_provider(name: str, settings: Settings) -> ChatProvider:
    """Create the adapter for an explicitly chosen provider. Never substitutes another one."""
    if name == "groq":
        if not settings.groq_api_key:
            raise ProviderNotConfiguredError(
                "GROQ_API_KEY is not set. Add your free key from https://console.groq.com/keys to .env",
                details={"provider": "groq"},
            )
        return OpenAICompatibleProvider(
            "groq", base_url=settings.groq_base_url, api_key=settings.groq_api_key, timeout=settings.llm_timeout_sec
        )
    if name == "openai":
        if not settings.openai_api_key:
            raise ProviderNotConfiguredError(
                "OpenAI is optional and not configured (OPENAI_API_KEY is empty). "
                "Use LLM_PROVIDER=groq for the free tier.",
                details={"provider": "openai"},
            )
        return OpenAICompatibleProvider(
            "openai", base_url=None, api_key=settings.openai_api_key, timeout=settings.llm_timeout_sec
        )
    if name == "ollama":
        # Ollama ignores the key, but the SDK requires a non-empty one.
        return OpenAICompatibleProvider(
            "ollama", base_url=settings.finetuned_base_url, api_key="ollama", timeout=settings.llm_timeout_sec
        )
    raise ProviderNotConfiguredError(f"Unknown LLM provider '{name}'", details={"provider": name})
