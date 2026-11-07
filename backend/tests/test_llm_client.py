"""LLM client wrapper: logging to llm_calls, JSON validation + repair, retries, and the
free-tier rule (no automatic fallback to a paid provider)."""

import json
import uuid
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.models.lecture import Lecture
from app.models.llmops import LLMCall
from app.models.user import User
from app.services.llm.client import LLMClient
from app.services.llm.errors import (
    LLMOutputInvalidError,
    ModelUnavailableError,
    ProviderNotConfiguredError,
    RateLimitedError,
)
from app.services.llm.pricing import PricingTable
from app.services.llm.prompts import PromptRegistry, PromptRenderError
from app.services.llm.providers import ProviderError
from tests.fakes import FakeProvider, ok, rate_limited

PROMPT_YAML = """\
id: demo
version: v3
description: test prompt
system: |
  You summarise. Use only the transcript.
user: |
  Transcript: ${transcript}
  Example of the shape: {"title": "..."}
"""


class TitleOut(BaseModel):
    title: str
    points: list[str]


@pytest.fixture
def prompts(tmp_path: Path) -> PromptRegistry:
    (tmp_path / "demo.yaml").write_text(PROMPT_YAML, encoding="utf-8")
    return PromptRegistry(tmp_path)


@pytest.fixture
def pricing() -> PricingTable:
    return PricingTable.model_validate(
        {
            "checked": "test",
            "providers": {
                "groq": {"billing": "free_tier", "models": {"openai/gpt-oss-120b": {"input": 0.15, "output": 0.6}}},
                "openai": {"billing": "paid", "models": {"gpt-5-mini": {"input": 0.25, "output": 2.0}}},
                "ollama": {"billing": "local"},
            },
        }
    )


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def make_client(settings, session_factory, prompts, pricing, sleeps):
    def _make(**providers: FakeProvider) -> LLMClient:
        return LLMClient(settings, session_factory, prompts, pricing, providers=providers, sleep=sleeps.append)

    return _make


def _rows(db) -> list[LLMCall]:
    db.expire_all()
    return list(db.scalars(select(LLMCall).order_by(LLMCall.attempt)))


# --- happy path + logging ---------------------------------------------------


def test_successful_call_writes_llm_calls_row(make_client, db):
    user = User(email="u@example.com", password_hash="x")
    db.add(user)
    db.flush()
    lecture = Lecture(user_id=user.id, title="Intro")
    db.add(lecture)
    db.commit()

    groq = FakeProvider("groq", [ok("Plain text answer", inp=1234, out=56)])
    client = make_client(groq=groq)

    result = client.complete(
        task="summary",
        prompt_id="demo",
        variables={"transcript": "cells divide"},
        user_id=user.id,
        lecture_id=lecture.id,
    )

    assert result.text == "Plain text answer"
    assert result.provider == "groq"  # LLM_PROVIDER default
    assert result.model == "openai/gpt-oss-120b"  # LLM_MODEL default
    assert result.prompt_version == "demo@v3"
    assert (result.input_tokens, result.output_tokens) == (1234, 56)
    assert result.cost_usd == 0.0  # Groq free tier

    # The prompt was rendered; literal JSON braces in the template survive.
    sent = groq.calls[0]["messages"]
    assert sent[0]["role"] == "system" and "Use only the transcript" in sent[0]["content"]
    assert "Transcript: cells divide" in sent[1]["content"]
    assert '{"title": "..."}' in sent[1]["content"]
    assert groq.calls[0]["json_mode"] is False

    [row] = _rows(db)
    assert row.id == result.call_ids[0]
    assert (row.task, row.provider, row.model) == ("summary", "groq", "openai/gpt-oss-120b")
    assert row.model_version == "fake-model-2026"
    assert (row.prompt_id, row.prompt_version) == ("demo", "demo@v3")
    assert (row.input_tokens, row.output_tokens) == (1234, 56)
    assert row.latency_ms is not None and row.latency_ms >= 0
    assert row.cost_usd == 0.0
    assert row.status == "ok"
    assert row.attempt == 1
    assert (row.user_id, row.lecture_id) == (user.id, lecture.id)
    assert row.error_type is None
    assert len(row.request_hash) == 64


def test_cost_is_calculated_from_tokens_for_paid_provider(make_client, db):
    openai_fake = FakeProvider("openai", [ok("hi", inp=1_000_000, out=500_000)])
    client = make_client(openai=openai_fake)

    result = client.complete(
        task="summary", prompt_id="demo", variables={"transcript": "t"}, provider="openai", model="gpt-5-mini"
    )

    assert result.cost_usd == pytest.approx(0.25 + 1.0)  # 1M in x $0.25 + 0.5M out x $2.00
    assert _rows(db)[0].cost_usd == pytest.approx(1.25)


def test_unknown_paid_model_cost_is_null_not_guessed(make_client, db):
    client = make_client(openai=FakeProvider("openai", [ok("hi")]))
    result = client.complete(
        task="t", prompt_id="demo", variables={"transcript": "t"}, provider="openai", model="some-new-model"
    )
    assert result.cost_usd is None
    assert _rows(db)[0].cost_usd is None


def test_missing_prompt_variable_raises(make_client):
    client = make_client(groq=FakeProvider("groq"))
    with pytest.raises(PromptRenderError, match="transcript"):
        client.complete(task="t", prompt_id="demo", variables={})


# --- JSON validation + one repair retry -------------------------------------


def test_json_output_is_validated_and_fences_are_tolerated(make_client, db):
    groq = FakeProvider("groq", [ok('```json\n{"title": "Mitosis", "points": ["a", "b"]}\n```')])
    client = make_client(groq=groq)

    result = client.complete(task="summary", prompt_id="demo", variables={"transcript": "t"}, schema=TitleOut)

    assert isinstance(result.data, TitleOut)
    assert result.data.title == "Mitosis"
    assert groq.calls[0]["json_mode"] is True
    assert '"title"' in groq.calls[0]["messages"][0]["content"]  # JSON Schema added to system prompt
    assert [r.status for r in _rows(db)] == ["ok"]


def test_invalid_json_gets_one_repair_retry(make_client, db):
    groq = FakeProvider(
        "groq",
        [
            ok('{"title": "Mitosis"}', inp=100, out=10),  # missing "points"
            ok('{"title": "Mitosis", "points": ["prophase"]}', inp=150, out=15),
        ],
    )
    client = make_client(groq=groq)

    result = client.complete(task="summary", prompt_id="demo", variables={"transcript": "t"}, schema=TitleOut)

    assert result.data.points == ["prophase"]
    assert (result.input_tokens, result.output_tokens) == (250, 25)  # both requests counted
    repair_msgs = groq.calls[1]["messages"]
    assert repair_msgs[-2] == {"role": "assistant", "content": '{"title": "Mitosis"}'}
    assert "points" in repair_msgs[-1]["content"]  # validation errors shown to the model

    rows = _rows(db)
    assert [(r.attempt, r.status) for r in rows] == [(1, "json_invalid"), (2, "ok")]
    assert len(result.call_ids) == 2


def test_json_invalid_twice_raises_and_logs_both(make_client, db):
    client = make_client(groq=FakeProvider("groq", [ok("not json at all"), ok('{"title": 5}')]))

    with pytest.raises(LLMOutputInvalidError) as exc_info:
        client.complete(task="quiz", prompt_id="demo", variables={"transcript": "t"}, schema=TitleOut)

    assert exc_info.value.code == "LLM_OUTPUT_INVALID"
    assert exc_info.value.status_code == 502
    assert [r.status for r in _rows(db)] == ["json_invalid", "json_invalid"]


# --- retries on 429 / outages, same provider only ---------------------------


def test_rate_limit_is_retried_with_exponential_backoff(make_client, db, sleeps):
    groq = FakeProvider("groq", [rate_limited(), rate_limited(), ok("finally")])
    client = make_client(groq=groq)

    result = client.complete(task="summary", prompt_id="demo", variables={"transcript": "t"})

    assert result.text == "finally"
    assert sleeps == [2.0, 4.0]  # base 2s, doubled
    rows = _rows(db)
    assert [(r.attempt, r.status) for r in rows] == [(1, "rate_limited"), (2, "rate_limited"), (3, "ok")]
    assert rows[0].error_type == "RateLimitError"


def test_retry_after_header_is_honoured_and_capped(make_client, sleeps):
    client = make_client(groq=FakeProvider("groq", [rate_limited(retry_after=7), rate_limited(retry_after=999), ok("x")]))
    client.complete(task="t", prompt_id="demo", variables={"transcript": "t"})
    assert sleeps == [7, 30.0]  # Retry-After used; capped at LLM_BACKOFF_MAX_SEC


def test_rate_limit_exhausted_raises_and_never_falls_back_to_openai(make_client, db, sleeps, settings):
    groq = FakeProvider("groq", [rate_limited()] * (settings.llm_max_retries + 1))
    paid = FakeProvider("openai", [ok("SHOULD NEVER BE USED")])
    client = make_client(groq=groq, openai=paid)

    with pytest.raises(RateLimitedError) as exc_info:
        client.complete(task="summary", prompt_id="demo", variables={"transcript": "t"})

    err = exc_info.value
    assert (err.code, err.status_code) == ("RATE_LIMITED", 429)
    assert "no paid fallback" in err.message
    assert len(groq.calls) == settings.llm_max_retries + 1
    assert paid.calls == []  # free-tier rule: no automatic fallback
    assert sleeps == [2.0, 4.0, 8.0]
    assert {r.provider for r in _rows(db)} == {"groq"}


def test_transient_outage_is_retried_then_reported_as_unavailable(make_client, db):
    outage = ProviderError("unavailable", "connection refused", error_type="APIConnectionError")
    client = make_client(groq=FakeProvider("groq", [outage] * 4))

    with pytest.raises(ModelUnavailableError) as exc_info:
        client.complete(task="t", prompt_id="demo", variables={"transcript": "t"})

    assert (exc_info.value.code, exc_info.value.status_code) == ("MODEL_UNAVAILABLE", 503)
    assert [r.status for r in _rows(db)] == ["unavailable"] * 4


def test_unknown_or_decommissioned_model_is_not_retried(make_client, db, sleeps):
    gone = ProviderError("model_not_found", "model_decommissioned", error_type="BadRequestError")
    client = make_client(groq=FakeProvider("groq", [gone]))

    with pytest.raises(ModelUnavailableError, match="not available on groq"):
        client.complete(task="t", prompt_id="demo", variables={"transcript": "t"}, model="llama-old")

    assert sleeps == []
    [row] = _rows(db)
    assert (row.status, row.model, row.error_type) == ("error", "llama-old", "BadRequestError")


# --- provider configuration -------------------------------------------------


def test_missing_groq_key_raises_not_configured_and_does_not_use_openai(settings, session_factory, prompts, pricing, db):
    no_key = settings.model_copy(update={"groq_api_key": "", "openai_api_key": "sk-would-cost-money"})
    client = LLMClient(no_key, session_factory, prompts, pricing)  # real provider builder, no fakes

    with pytest.raises(ProviderNotConfiguredError, match="GROQ_API_KEY"):
        client.complete(task="t", prompt_id="demo", variables={"transcript": "t"})

    [row] = _rows(db)
    assert (row.provider, row.status) == ("groq", "not_configured")


def test_openai_is_opt_in_and_needs_its_own_key(settings, session_factory, prompts, pricing):
    client = LLMClient(settings, session_factory, prompts, pricing)  # OPENAI_API_KEY is empty in tests
    with pytest.raises(ProviderNotConfiguredError, match="OpenAI is optional"):
        client.complete(task="t", prompt_id="demo", variables={"transcript": "t"}, provider="openai")


def test_ollama_defaults_to_finetuned_model_tag(make_client, settings):
    ollama = FakeProvider("ollama", [ok("answer")])
    result = make_client(ollama=ollama).complete(
        task="rag_answer", prompt_id="demo", variables={"transcript": "t"}, provider="ollama"
    )
    assert result.model == settings.finetuned_model_tag
    assert result.cost_usd == 0.0  # local


def test_logging_failure_does_not_break_the_call(settings, prompts, pricing):
    def broken_session_factory():
        raise RuntimeError("database down")

    client = LLMClient(
        settings, broken_session_factory, prompts, pricing, providers={"groq": FakeProvider("groq", [ok("still works")])}
    )
    result = client.complete(task="t", prompt_id="demo", variables={"transcript": "t"})
    assert result.text == "still works"
    assert result.call_ids == []


def test_request_hash_is_stable_for_identical_requests(make_client, db):
    client = make_client(groq=FakeProvider("groq", [ok("a"), ok("b")]))
    for _ in range(2):
        client.complete(task="t", prompt_id="demo", variables={"transcript": "same"})
    rows = _rows(db)
    assert rows[0].request_hash == rows[1].request_hash
    assert uuid.UUID(str(rows[0].id)) != rows[1].id


def test_schema_instruction_is_valid_json_schema(make_client):
    groq = FakeProvider("groq", [ok('{"title": "x", "points": []}')])
    make_client(groq=groq).complete(task="t", prompt_id="demo", variables={"transcript": "t"}, schema=TitleOut)
    system = groq.calls[0]["messages"][0]["content"]
    schema = json.loads(system.split("JSON Schema:\n", 1)[1])
    assert set(schema["required"]) == {"title", "points"}
