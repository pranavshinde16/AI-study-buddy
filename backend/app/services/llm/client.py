"""The single entry point for LLM calls (CLAUDE.md rule 4).

    result = client.complete(task="summary", prompt_id="summary", variables={...}, schema=SummaryOut)

What it does, in order:
1. Loads the versioned prompt and renders it.
2. Picks the provider: the explicit `provider=` argument, else LLM_PROVIDER (groq by default).
   It NEVER switches to another provider on failure (free-tier rule, CLAUDE.md 12).
3. Sends the request. On 429 / transient errors it retries the SAME provider with exponential
   backoff (honouring Retry-After), up to LLM_MAX_RETRIES times.
4. If `schema` is given: asks for JSON, validates it with Pydantic, and on failure makes ONE
   repair request that shows the model its validation errors.
5. Writes one `llm_calls` row per request sent (tokens, latency, cost, prompt version, status).
"""

import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models.llmops import LLMCall
from app.services.llm.errors import (
    LLMError,
    LLMOutputInvalidError,
    ModelUnavailableError,
    ProviderNotConfiguredError,
    RateLimitedError,
)
from app.services.llm.calllog import save_call
from app.services.llm.pricing import PricingTable
from app.services.llm.prompts import PromptRegistry, PromptTemplate
from app.services.llm.providers import ChatProvider, ChatResult, ProviderError, build_provider
from app.services.llm.ratelimit import Reservation, TokenRateLimiter, estimate_tokens
from app.services.llm.retry import backoff_delay

log = structlog.get_logger(__name__)

# Providers whose models accept `reasoning_effort` (gpt-oss on Groq, gpt-5 on OpenAI). Not Ollama.
REASONING_PROVIDERS = frozenset({"groq", "openai"})
# ...and only their reasoning models: e.g. qwen/qwen3.8-27b (the Phase 11 eval judge)
# is not one, and sending the parameter to it would be rejected.
REASONING_MODEL_PREFIXES = ("openai/gpt-oss", "gpt-oss", "gpt-5", "o1", "o3", "o4")


def supports_reasoning_effort(provider: str, model: str) -> bool:
    return provider in REASONING_PROVIDERS and model.lower().startswith(REASONING_MODEL_PREFIXES)
# Output tokens reserved for pacing before the real count is known.
OUTPUT_RESERVE_TOKENS = 1000

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)  # qwen3 (Ollama) can emit its reasoning first


@dataclass
class LLMResult:
    text: str
    data: BaseModel | None
    provider: str
    model: str
    model_version: str | None
    prompt_id: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float | None = 0.0
    call_ids: list[uuid.UUID] = field(default_factory=list)


def _extract_json(text: str) -> Any:
    """Parse JSON, tolerating ```json fences or prose around a single object."""
    candidate = _THINK.sub("", text).strip()
    m = _FENCE.match(candidate)
    if m:
        candidate = m.group(1)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end > start:
            return json.loads(candidate[start : end + 1])
        raise


def _schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "\n\nRespond with a single JSON object only (no markdown, no commentary) that validates "
        "against this JSON Schema:\n" + json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session] | Callable[[], Session],
        prompts: PromptRegistry,
        pricing: PricingTable,
        providers: dict[str, ChatProvider] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rate_limiters: dict[str, TokenRateLimiter] | None = None,
        version_resolver: Callable[[str, str, str | None], str | None] | None = None,
    ) -> None:
        self.settings = settings
        # (provider, model, reported) -> stored model_version. None = store what the provider
        # reported. The app wires in model_info.ModelVersionResolver (adds the Ollama digest).
        self._version_resolver = version_resolver
        self._session_factory = session_factory
        self.prompts = prompts
        self.pricing = pricing
        self._providers: dict[str, ChatProvider] = dict(providers or {})
        self._sleep = sleep
        # Per-provider tokens-per-minute pacing. Only Groq's free tier needs it by default.
        self._limiters: dict[str, TokenRateLimiter] = (
            dict(rate_limiters)
            if rate_limiters is not None
            else {"groq": TokenRateLimiter(settings.groq_tokens_per_minute, sleep=sleep)}
        )

    # ------------------------------------------------------------------ public API

    def complete(
        self,
        *,
        task: str,
        prompt_id: str,
        variables: dict[str, Any] | None = None,
        schema: type[BaseModel] | None = None,
        provider: str | None = None,
        model: str | None = None,
        user_id: uuid.UUID | None = None,
        lecture_id: uuid.UUID | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        max_retries: int | None = None,
    ) -> LLMResult:
        """`max_retries` overrides LLM_MAX_RETRIES for this call (e.g. 0 for a local Ollama
        model, where waiting and retrying a refused connection only delays the error)."""
        prompt = self.prompts.get(prompt_id)
        system, user = prompt.render(variables or {})
        if schema is not None:
            system += _schema_instruction(schema)

        provider_name = provider or self.settings.llm_provider
        model_name = model or prompt.model or self._default_model(provider_name)
        ctx = _CallContext(
            task=task,
            prompt=prompt,
            provider=provider_name,
            model=model_name,
            user_id=user_id,
            lecture_id=lecture_id,
            json_mode=schema is not None,
            max_output_tokens=max_output_tokens or prompt.max_output_tokens or self.settings.llm_max_output_tokens,
            temperature=temperature if temperature is not None else prompt.temperature,
            reasoning_effort=((self.settings.llm_reasoning_effort or None)
                              if supports_reasoning_effort(provider_name, model_name) else None),
            max_retries=max_retries,
        )
        try:
            chat_provider = self._get_provider(provider_name)
        except ProviderNotConfiguredError as exc:
            self._log_call(ctx, attempt=1, messages=[], status="not_configured", error=exc)
            raise

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        result = LLMResult(
            text="",
            data=None,
            provider=provider_name,
            model=model_name,
            model_version=None,
            prompt_id=prompt.id,
            prompt_version=prompt.tag,
        )

        chat = self._send_with_retries(chat_provider, ctx, messages, result, json_check=schema)
        if schema is None:
            result.text = chat.text
            return result

        data, error = self._validate(chat.text, schema)
        if data is None:
            # One repair attempt: show the model its own output and the validation errors.
            repair_messages = [
                *messages,
                {"role": "assistant", "content": chat.text},
                {
                    "role": "user",
                    "content": (
                        "Your previous reply was not valid for the required JSON Schema.\n"
                        f"Errors: {error}\n"
                        "Reply again with ONLY the corrected JSON object."
                    ),
                },
            ]
            chat = self._send_with_retries(chat_provider, ctx, repair_messages, result, json_check=schema, repair=True)
            data, error = self._validate(chat.text, schema)
            if data is None:
                raise LLMOutputInvalidError(
                    "The model returned invalid JSON twice; please try again.",
                    details={"task": task, "prompt_version": prompt.tag, "validation_error": error},
                )

        result.text = chat.text
        result.data = data
        return result

    # ------------------------------------------------------------------ internals

    def _default_model(self, provider_name: str) -> str:
        if provider_name == "ollama":
            return self.settings.finetuned_model_tag
        return self.settings.llm_model

    def _get_provider(self, name: str) -> ChatProvider:
        if name not in self._providers:
            self._providers[name] = build_provider(name, self.settings)
        return self._providers[name]

    @staticmethod
    def _validate(text: str, schema: type[BaseModel]) -> tuple[BaseModel | None, str | None]:
        try:
            return schema.model_validate(_extract_json(text)), None
        except json.JSONDecodeError as exc:
            return None, f"not JSON ({exc.msg})"
        except ValidationError as exc:
            return None, exc.json(include_url=False)[:2000]

    def _backoff(self, retry_index: int, retry_after: float | None) -> float:
        return backoff_delay(self.settings, retry_index, retry_after)

    def _send_with_retries(
        self,
        chat_provider: ChatProvider,
        ctx: "_CallContext",
        messages: list[dict[str, str]],
        result: LLMResult,
        *,
        json_check: type[BaseModel] | None,
        repair: bool = False,
    ) -> ChatResult:
        retries = self.settings.llm_max_retries if ctx.max_retries is None else ctx.max_retries
        for retry_index in range(retries + 1):
            ctx.attempt += 1
            reservation = self._pace(ctx, messages)
            start = time.perf_counter()
            try:
                chat = chat_provider.chat(
                    model=ctx.model,
                    messages=messages,
                    json_mode=ctx.json_mode,
                    max_output_tokens=ctx.max_output_tokens,
                    temperature=ctx.temperature,
                    reasoning_effort=ctx.reasoning_effort,
                )
            except ProviderError as exc:
                self._settle(ctx, reservation, None)
                latency = (time.perf_counter() - start) * 1000
                status = "rate_limited" if exc.kind == "rate_limited" else "unavailable" if exc.retryable else "error"
                self._log_call(ctx, attempt=ctx.attempt, messages=messages, status=status, error=exc, latency_ms=latency)
                if exc.retryable and retry_index < retries:
                    delay = self._backoff(retry_index, exc.retry_after)
                    log.warning(
                        "llm_retry",
                        provider=ctx.provider,
                        model=ctx.model,
                        kind=exc.kind,
                        retry_in_sec=delay,
                        retry=retry_index + 1,
                        max_retries=retries,
                    )
                    self._sleep(delay)
                    continue
                raise self._to_app_error(exc, ctx) from exc

            latency = (time.perf_counter() - start) * 1000
            if self._version_resolver is not None:
                try:
                    chat.model_version = self._version_resolver(ctx.provider, ctx.model, chat.model_version)
                except Exception as exc:  # noqa: BLE001 - version metadata must never fail a request
                    log.info("model_version_lookup_failed", provider=ctx.provider, error_type=type(exc).__name__)
            if chat.input_tokens is not None or chat.output_tokens is not None:
                self._settle(ctx, reservation, (chat.input_tokens or 0) + (chat.output_tokens or 0))
            cost = self.pricing.cost(ctx.provider, ctx.model, chat.input_tokens, chat.output_tokens)
            status = "ok"
            err_msg = None
            if json_check is not None and self._validate(chat.text, json_check)[0] is None:
                status = "json_invalid"
                err_msg = "output failed schema validation" + (" (after repair)" if repair else "")
            call_id = self._log_call(
                ctx,
                attempt=ctx.attempt,
                messages=messages,
                status=status,
                latency_ms=latency,
                chat=chat,
                cost_usd=cost,
                error_message=err_msg,
            )
            result.model_version = chat.model_version
            result.input_tokens += chat.input_tokens or 0
            result.output_tokens += chat.output_tokens or 0
            result.latency_ms += latency
            result.cost_usd = None if cost is None or result.cost_usd is None else result.cost_usd + cost
            if call_id is not None:
                result.call_ids.append(call_id)
            return chat
        raise AssertionError("unreachable")  # pragma: no cover

    def _pace(self, ctx: "_CallContext", messages: list[dict[str, str]]) -> Reservation | None:
        """Wait if this request would push the provider over its tokens-per-minute limit."""
        limiter = self._limiters.get(ctx.provider)
        if limiter is None:
            return None
        estimate = estimate_tokens(messages) + min(ctx.max_output_tokens, OUTPUT_RESERVE_TOKENS)
        reservation, waited = limiter.acquire(estimate)
        if waited > 0:
            log.info("llm_rate_wait", provider=ctx.provider, model=ctx.model, task=ctx.task,
                     waited_sec=round(waited, 2), estimated_tokens=estimate)
        return reservation

    def _settle(self, ctx: "_CallContext", reservation: Reservation | None, actual: int | None) -> None:
        limiter = self._limiters.get(ctx.provider)
        if limiter is not None:
            limiter.settle(reservation, actual)

    def _to_app_error(self, exc: ProviderError, ctx: "_CallContext") -> LLMError:
        details = {"provider": ctx.provider, "model": ctx.model, "task": ctx.task}
        if ctx.provider == "ollama" and exc.kind in ("unavailable", "model_not_found"):
            url = self.settings.finetuned_base_url
            if exc.kind == "unavailable":
                message = (f"Ollama is not running or not reachable at {url} (FINETUNED_BASE_URL). Start it with "
                           "`ollama serve`; the fine-tuned and base SLMs are set up in Phase 10.")
            else:
                message = (f"Model '{ctx.model}' is not installed in Ollama at {url}. Pull or create it first "
                           f"(`ollama pull {ctx.model}`, or `ollama create` for the fine-tuned model in Phase 10).")
            return ModelUnavailableError(message, details={**details, "base_url": url})
        if exc.kind == "rate_limited":
            return RateLimitedError(
                f"{ctx.provider} rate limit reached for {ctx.model}. Wait a minute and try again "
                "(free-tier limits apply; no paid fallback is used).",
                retry_after=exc.retry_after,
                details=details,
            )
        if exc.kind == "model_not_found":
            return ModelUnavailableError(
                f"Model '{ctx.model}' is not available on {ctx.provider}. Check LLM_MODEL in .env "
                "against the provider's current model list.",
                details=details,
            )
        if exc.kind == "unavailable":
            return ModelUnavailableError(f"{ctx.provider} is unreachable or overloaded. Try again shortly.", details=details)
        if exc.kind == "auth":
            return ProviderNotConfiguredError(f"{ctx.provider} rejected the API key. Check it in .env.", details=details)
        return LLMError(f"{ctx.provider} request failed: {exc.error_type}", details=details)

    def _log_call(
        self,
        ctx: "_CallContext",
        *,
        attempt: int,
        messages: list[dict[str, str]],
        status: str,
        latency_ms: float | None = None,
        chat: ChatResult | None = None,
        cost_usd: float | None = None,
        error: Exception | None = None,
        error_message: str | None = None,
    ) -> uuid.UUID | None:
        request_hash = hashlib.sha256(
            json.dumps({"p": ctx.provider, "m": ctx.model, "msgs": messages}, sort_keys=True).encode("utf-8")
        ).hexdigest()
        row = LLMCall(
            user_id=ctx.user_id,
            lecture_id=ctx.lecture_id,
            task=ctx.task,
            provider=ctx.provider,
            model=ctx.model,
            model_version=chat.model_version if chat else None,
            prompt_id=ctx.prompt.id,
            prompt_version=ctx.prompt.tag,
            attempt=attempt,
            input_tokens=chat.input_tokens if chat else None,
            output_tokens=chat.output_tokens if chat else None,
            latency_ms=round(latency_ms, 2) if latency_ms is not None else None,
            cost_usd=cost_usd,
            status=status,
            error_type=(getattr(error, "error_type", None) or type(error).__name__) if error else None,
            error_message=(getattr(error, "message", None) or str(error))[:2000] if error else error_message,
            request_hash=request_hash,
        )
        log.info(
            "llm_call",
            task=ctx.task,
            provider=ctx.provider,
            model=ctx.model,
            prompt_version=ctx.prompt.tag,
            attempt=attempt,
            status=status,
            latency_ms=row.latency_ms,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cost_usd=cost_usd,
        )
        # Logging must never break the user's request (see calllog.save_call).
        return save_call(self._session_factory, row)


@dataclass
class _CallContext:
    task: str
    prompt: PromptTemplate
    provider: str
    model: str
    user_id: uuid.UUID | None
    lecture_id: uuid.UUID | None
    json_mode: bool
    max_output_tokens: int
    temperature: float | None
    reasoning_effort: str | None = None
    max_retries: int | None = None
    attempt: int = 0


@lru_cache
def get_llm_client() -> LLMClient:
    """FastAPI dependency / default factory wired to the real DB, prompts and pricing.
    Tests override it (app.dependency_overrides) with a client that uses fake providers."""
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.services.llm.model_info import ModelVersionResolver, get_ollama_info
    from app.services.llm.pricing import get_pricing
    from app.services.llm.prompts import get_prompt_registry

    settings = get_settings()
    resolver = ModelVersionResolver(get_ollama_info(settings.finetuned_base_url))
    return LLMClient(settings, get_session_factory(), get_prompt_registry(), get_pricing(),
                     version_resolver=resolver)
