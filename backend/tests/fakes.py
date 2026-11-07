"""Fake LLM provider for tests: plays back a scripted list of results or errors. No network."""

from app.services.llm.providers import ChatResult, ProviderError


class FakeProvider:
    def __init__(self, name: str, script: list[ChatResult | ProviderError] | None = None) -> None:
        self.name = name
        self.script = list(script or [])
        self.calls: list[dict] = []

    def chat(self, *, model, messages, json_mode, max_output_tokens, temperature) -> ChatResult:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "json_mode": json_mode,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
            }
        )
        if not self.script:
            raise AssertionError(f"FakeProvider '{self.name}' called more times than scripted")
        item = self.script.pop(0)
        if isinstance(item, ProviderError):
            raise item
        return item


def ok(text: str, *, model_version: str = "fake-model-2026", inp: int = 100, out: int = 20) -> ChatResult:
    return ChatResult(text=text, model_version=model_version, input_tokens=inp, output_tokens=out)


def rate_limited(retry_after: float | None = None) -> ProviderError:
    return ProviderError("rate_limited", "429 Too Many Requests", error_type="RateLimitError", retry_after=retry_after)
