"""Backoff rule shared by the LLM and ASR clients (same provider only, never a fallback)."""

from app.core.config import Settings


def backoff_delay(settings: Settings, retry_index: int, retry_after: float | None) -> float:
    """Seconds to wait before retry number `retry_index + 1`.

    Uses the provider's Retry-After header when given, else LLM_BACKOFF_BASE_SEC * 2**retry_index,
    capped at LLM_BACKOFF_MAX_SEC.
    """
    delay = retry_after if retry_after is not None else settings.llm_backoff_base_sec * (2**retry_index)
    return min(delay, settings.llm_backoff_max_sec)
