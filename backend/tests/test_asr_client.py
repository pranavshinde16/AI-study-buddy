"""ASR client: verbose_json parsing, logging to llm_calls, same-provider retries, no paid fallback."""

import importlib.util
from types import SimpleNamespace

import httpx2
import openai
import pytest
from sqlalchemy import select

from app.models.llmops import LLMCall
from app.services.asr.client import ASRClient
from app.services.asr.providers import OpenAICompatibleWhisper, build_asr_provider, parse_verbose_json
from app.services.llm.errors import LLMError, ModelUnavailableError, ProviderNotConfiguredError, RateLimitedError
from app.services.llm.pricing import load_pricing
from app.services.llm.providers import ProviderError
from tests.fakes import FakeASRProvider, asr_ok, rate_limited

REQ = httpx2.Request("POST", "https://api.groq.test/openai/v1/audio/transcriptions")


def _rows(db) -> list[LLMCall]:
    return list(db.scalars(select(LLMCall).order_by(LLMCall.attempt)))


def _whisper(create) -> OpenAICompatibleWhisper:
    w = OpenAICompatibleWhisper("groq", base_url="https://api.groq.test/openai/v1", api_key="k", timeout=5)
    w._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    return w


@pytest.fixture
def chunk(tmp_path):
    p = tmp_path / "chunk_000.flac"
    p.write_bytes(b"fake audio")
    return p


def test_parse_verbose_json_from_dict_and_object():
    d = {"language": "english", "duration": 12.5, "segments": [{"start": 0, "end": 2.2, "text": "  Hi  "}]}
    r = parse_verbose_json(d)
    assert (r.language, r.duration_sec, r.segments[0].start, r.segments[0].end, r.segments[0].text) == (
        "english", 12.5, 0.0, 2.2, "Hi",
    )
    obj = SimpleNamespace(language="en", duration=None, segments=[SimpleNamespace(start=1, end=2, text="x")])
    assert parse_verbose_json(obj).segments[0].start == 1.0


def test_whisper_adapter_request_shape(chunk):
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(text="hi", language="en", duration=2.0, segments=[SimpleNamespace(start=0, end=2, text="hi")])

    result = _whisper(create).transcribe(chunk, model="whisper-large-v3-turbo", language="en")

    assert seen["response_format"] == "verbose_json"
    assert seen["timestamp_granularities"] == ["segment"]
    assert seen["model"] == "whisper-large-v3-turbo" and seen["language"] == "en"
    assert seen["file"][0] == "chunk_000.flac"
    assert result.segments[0].text == "hi"


def test_whisper_adapter_translates_sdk_errors(chunk):
    def create(**_):
        raise openai.RateLimitError(
            "slow", response=httpx2.Response(429, headers={"retry-after": "4"}, request=REQ), body=None
        )

    with pytest.raises(ProviderError) as exc:
        _whisper(create).transcribe(chunk, model="m", language=None)
    assert (exc.value.kind, exc.value.retry_after) == ("rate_limited", 4.0)


def test_text_without_segments_is_rejected_not_invented(chunk):
    w = _whisper(lambda **_: SimpleNamespace(text="words", language="en", duration=1.0, segments=None))
    with pytest.raises(ProviderError, match="no segment timestamps"):
        w.transcribe(chunk, model="m", language=None)


def test_success_is_logged_as_free_asr_call(asr_client, fake_asr, chunk, db):
    fake_asr.script = [asr_ok((0, 1.5, "hello"), duration=600.0)]
    result = asr_client.transcribe_chunk(chunk, audio_sec=600.0)

    assert result.segments[0].text == "hello"
    assert fake_asr.calls[0]["model"] == "whisper-large-v3-turbo"
    [row] = _rows(db)
    assert (row.task, row.provider, row.model, row.status, row.attempt, row.cost_usd) == (
        "asr", "groq", "whisper-large-v3-turbo", "ok", 1, 0.0,
    )
    assert row.latency_ms is not None and row.prompt_id is None


def test_rate_limit_retries_same_provider_with_backoff(settings, session_factory, chunk, db):
    fake = FakeASRProvider("groq", script=[rate_limited(retry_after=3), rate_limited(), asr_ok((0, 1, "ok"))])
    waits: list[float] = []
    client = ASRClient(settings, session_factory, load_pricing(), providers={"groq": fake}, sleep=waits.append)

    client.transcribe_chunk(chunk, audio_sec=10)

    assert waits == [3, 4.0]  # Retry-After honoured, then base 2 * 2**1
    assert [(r.attempt, r.status) for r in _rows(db)] == [(1, "rate_limited"), (2, "rate_limited"), (3, "ok")]


def test_rate_limit_exhausted_never_falls_back_to_openai(settings, session_factory, chunk, db):
    settings.openai_api_key = "sk-would-cost-money"
    groq = FakeASRProvider("groq", script=[rate_limited()] * 4)
    openai_fake = FakeASRProvider("openai", script=[])
    client = ASRClient(
        settings, session_factory, load_pricing(), providers={"groq": groq, "openai": openai_fake}, sleep=lambda _s: None
    )

    with pytest.raises(RateLimitedError) as exc:
        client.transcribe_chunk(chunk, audio_sec=10)

    assert exc.value.status_code == 429 and "no paid fallback" in exc.value.message
    assert len(groq.calls) == 4 and openai_fake.calls == []
    assert {r.provider for r in _rows(db)} == {"groq"}


def test_model_not_found_is_not_retried(asr_client, fake_asr, chunk):
    fake_asr.script = [ProviderError("model_not_found", "gone", error_type="NotFoundError")]
    with pytest.raises(ModelUnavailableError, match="ASR_MODEL"):
        asr_client.transcribe_chunk(chunk, audio_sec=1)
    assert len(fake_asr.calls) == 1


def test_bad_request_becomes_llm_error(asr_client, fake_asr, chunk):
    fake_asr.script = [ProviderError("bad_request", "file too large", error_type="BadRequestError")]
    with pytest.raises(LLMError) as exc:
        asr_client.transcribe_chunk(chunk, audio_sec=1)
    assert exc.value.status_code == 502


def test_openai_asr_needs_explicit_key(settings):
    settings.openai_api_key = ""
    with pytest.raises(ProviderNotConfiguredError, match="optional"):
        build_asr_provider("openai", settings)


def test_paid_openai_cost_uses_audio_minutes(settings, session_factory, chunk, db):
    settings.asr_provider = "openai"
    settings.openai_api_key = "sk-test"
    fake = FakeASRProvider("openai", script=[asr_ok((0, 1, "x"), duration=120.0)])
    client = ASRClient(settings, session_factory, load_pricing(), providers={"openai": fake})

    client.transcribe_chunk(chunk, audio_sec=120.0)

    [row] = _rows(db)
    assert row.model == "whisper-1" and row.cost_usd == pytest.approx(2 * 0.006)


@pytest.mark.skipif(importlib.util.find_spec("faster_whisper") is not None, reason="faster-whisper is installed")
def test_local_provider_without_faster_whisper(settings, session_factory, chunk, db):
    settings.asr_provider = "local"
    client = ASRClient(settings, session_factory, load_pricing())
    with pytest.raises(ProviderNotConfiguredError, match="requirements-asr-local.txt"):
        client.transcribe_chunk(chunk, audio_sec=1)
    [row] = _rows(db)
    assert (row.provider, row.model, row.status) == ("local", "small", "not_configured")


def test_missing_groq_key_logs_not_configured(settings, session_factory, chunk, db):
    settings.groq_api_key = ""
    client = ASRClient(settings, session_factory, load_pricing())
    with pytest.raises(ProviderNotConfiguredError, match="GROQ_API_KEY"):
        client.transcribe_chunk(chunk, audio_sec=1)
    assert _rows(db)[0].status == "not_configured"
