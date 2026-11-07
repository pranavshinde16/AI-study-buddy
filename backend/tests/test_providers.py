"""The OpenAI-compatible adapter: request shape and SDK error translation (SDK is mocked, no network)."""

from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.services.llm.errors import ProviderNotConfiguredError
from app.services.llm.providers import OpenAICompatibleProvider, ProviderError, build_provider

REQ = httpx2.Request("POST", "https://api.groq.test/openai/v1/chat/completions")


def _provider_with(create) -> OpenAICompatibleProvider:
    p = OpenAICompatibleProvider("groq", base_url="https://api.groq.test/openai/v1", api_key="k", timeout=5)
    p._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return p


def test_request_shape_and_usage_parsing():
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            model="openai/gpt-oss-120b-2026",
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3),
        )

    result = _provider_with(create).chat(
        model="openai/gpt-oss-120b", messages=[{"role": "user", "content": "hi"}], json_mode=True,
        max_output_tokens=256, temperature=None,
    )

    assert seen["model"] == "openai/gpt-oss-120b"
    assert seen["max_completion_tokens"] == 256
    assert seen["response_format"] == {"type": "json_object"}
    assert "temperature" not in seen  # only sent when the prompt sets it
    assert (result.text, result.model_version, result.input_tokens, result.output_tokens) == (
        '{"a": 1}', "openai/gpt-oss-120b-2026", 11, 3,
    )


@pytest.mark.parametrize(
    ("exc", "kind", "retry_after"),
    [
        (openai.RateLimitError("slow down", response=httpx2.Response(429, headers={"retry-after": "7"}, request=REQ), body=None), "rate_limited", 7.0),
        (openai.NotFoundError("no such model", response=httpx2.Response(404, request=REQ), body=None), "model_not_found", None),
        (openai.BadRequestError("model_decommissioned", response=httpx2.Response(400, request=REQ), body=None), "model_not_found", None),
        (openai.BadRequestError("bad param", response=httpx2.Response(400, request=REQ), body=None), "bad_request", None),
        (openai.AuthenticationError("bad key", response=httpx2.Response(401, request=REQ), body=None), "auth", None),
        (openai.InternalServerError("oops", response=httpx2.Response(503, request=REQ), body=None), "unavailable", None),
        (openai.APIConnectionError(request=REQ), "unavailable", None),
    ],
)
def test_sdk_errors_are_translated(exc, kind, retry_after):
    def create(**_):
        raise exc

    with pytest.raises(ProviderError) as info:
        _provider_with(create).chat(model="m", messages=[], json_mode=False, max_output_tokens=1, temperature=None)
    assert info.value.kind == kind
    assert info.value.retry_after == retry_after


def test_build_provider_requires_keys_and_never_substitutes(settings):
    assert build_provider("groq", settings).name == "groq"
    assert build_provider("ollama", settings).name == "ollama"  # local, no key needed
    with pytest.raises(ProviderNotConfiguredError):
        build_provider("openai", settings)  # empty OPENAI_API_KEY -> error, not a Groq substitute
    with pytest.raises(ProviderNotConfiguredError):
        build_provider("groq", settings.model_copy(update={"groq_api_key": ""}))
    with pytest.raises(ProviderNotConfiguredError, match="Unknown"):
        build_provider("anthropic", settings)
