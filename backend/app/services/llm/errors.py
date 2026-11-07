"""User-facing LLM errors (all use the API error envelope).

Free-tier rule (CLAUDE.md 12): these are raised instead of switching to another provider.
"""

from typing import Any

from fastapi import status

from app.core.errors import AppError


class LLMError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "LLM_ERROR"


class RateLimitedError(LLMError):
    """The provider kept returning 429 after all retries."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        if retry_after is not None:
            kwargs.setdefault("headers", {"Retry-After": str(int(retry_after) + 1)})
        super().__init__(message, **kwargs)


class ModelUnavailableError(LLMError):
    """Provider unreachable, model not found/decommissioned, or persistent 5xx."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "MODEL_UNAVAILABLE"


class ProviderNotConfiguredError(LLMError):
    """Missing API key or unknown provider; nothing was sent."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "PROVIDER_NOT_CONFIGURED"


class LLMOutputInvalidError(LLMError):
    """The model's output did not match the expected JSON schema, even after one repair attempt."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "LLM_OUTPUT_INVALID"
