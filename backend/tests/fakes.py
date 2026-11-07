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


# ---------------------------------------------------------------------------- speech recognition

from pathlib import Path  # noqa: E402

from app.services.asr.providers import ASRResult, ASRSegment  # noqa: E402


class FakeASRProvider:
    """Scripted ASR provider. With no script it returns two segments per chunk:
    0.0–1.0 "part <n> hello" and 1.0–1.9 "part <n> world". `on_call(path)` runs before each reply."""

    def __init__(self, name: str = "groq", script: list[ASRResult | ProviderError] | None = None, on_call=None) -> None:
        self.name = name
        self.script = list(script) if script is not None else None
        self.calls: list[dict] = []
        self.on_call = on_call

    def transcribe(self, path: Path, *, model: str, language: str | None) -> ASRResult:
        self.calls.append({"path": Path(path), "model": model, "language": language})
        if self.on_call is not None:
            self.on_call(Path(path))
        if self.script is None:
            n = len(self.calls)
            return ASRResult(
                segments=[ASRSegment(0.0, 1.0, f"part {n} hello"), ASRSegment(1.0, 1.9, f"part {n} world")],
                language="en",
            )
        if not self.script:
            raise AssertionError(f"FakeASRProvider '{self.name}' called more times than scripted")
        item = self.script.pop(0)
        if isinstance(item, ProviderError):
            raise item
        return item


def asr_ok(*segments: tuple[float, float, str], language: str = "en", duration: float | None = None) -> ASRResult:
    return ASRResult(segments=[ASRSegment(s, e, t) for s, e, t in segments], language=language, duration_sec=duration)
