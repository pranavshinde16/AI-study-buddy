"""Fake LLM provider for tests: plays back a scripted list of results or errors. No network."""

from app.services.llm.providers import ChatResult, ProviderError


class FakeProvider:
    def __init__(self, name: str, script: list[ChatResult | ProviderError] | None = None, responder=None) -> None:
        self.name = name
        self.script = list(script or [])
        self.responder = responder
        self.calls: list[dict] = []

    def chat(self, *, model, messages, json_mode, max_output_tokens, temperature, reasoning_effort=None) -> ChatResult:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "json_mode": json_mode,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "reasoning_effort": reasoning_effort,
            }
        )
        if self.responder is not None:  # a function of the messages -> reply (see FakeLectureLLM)
            item = self.responder(messages)
            if isinstance(item, ProviderError):
                raise item
            return item
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


# ---------------------------------------------------------------------------- lecture LLM (Phase 5)

import json  # noqa: E402
import re  # noqa: E402

_RANGE = re.compile(r"segments \[(\d+)\] to \[(\d+)\]")


class FakeLectureLLM:
    """Responder for FakeProvider: answers the topics / notes / summary prompts with valid JSON.

    It recognises the prompt from the JSON Schema the client appends to the system message.
    `topics`: splits the window's segment range into two topics (deliberately overlapping and
    one id out of range, to exercise the app's clamping) plus one definition on the first id.
    Set `fail[task] = ProviderError(...)` to make a task fail, or `invalid[task] = True` to
    return JSON that does not match the schema.
    """

    def __init__(self) -> None:
        self.tasks: list[str] = []
        self.user_messages: list[str] = []
        self.fail: dict[str, ProviderError] = {}
        self.invalid: dict[str, bool] = {}

    @staticmethod
    def task_of(system: str) -> str:
        if '"start_segment"' in system:
            return "topics"
        if '"notes_md"' in system:
            return "notes"
        if '"key_takeaways"' in system:
            return "summary"
        return "other"

    def __call__(self, messages):
        system, user = messages[0]["content"], messages[1]["content"]
        task = self.task_of(system)
        self.tasks.append(task)
        self.user_messages.append(user)
        if task in self.fail:
            return self.fail[task]
        if self.invalid.get(task):
            return ok('{"unexpected": true}')
        if task == "topics":
            lo, hi = (int(x) for x in _RANGE.search(user).groups())
            mid = (lo + hi) // 2
            body = {
                "topics": [
                    {"title": f"Topic {lo}", "start_segment": lo, "end_segment": mid + 1, "key_points": [f"point {lo}"]},
                    {"title": f"Topic {mid}", "start_segment": mid, "end_segment": hi + 50, "key_points": [f"point {mid}"]},
                ],
                "definitions": [
                    {"term": f"Term {lo}", "definition": "as explained (not stated in lecture)", "segment_id": lo},
                    {"term": "Ghost", "definition": "id outside the window", "segment_id": hi + 999},
                ],
            }
        elif task == "notes":
            topic = re.search(r"Topic: (.*)", user).group(1)
            body = {"notes_md": f"- **{topic}** notes from the transcript"}
        elif task == "summary":
            body = {"summary": "The lecture covers the topics.", "key_takeaways": ["Takeaway one", "Takeaway two"],
                    "revision_notes_md": "- revise **this**"}
        else:
            body = {}
        return ok(json.dumps(body), model_version="openai/gpt-oss-120b", inp=300, out=120)
