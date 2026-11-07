"""Client-side tokens-per-minute pacing for Groq's free tier."""

import pytest

from app.services.llm.client import LLMClient
from app.services.llm.pricing import load_pricing
from app.services.llm.prompts import PromptRegistry
from app.services.llm.ratelimit import TokenRateLimiter, estimate_tokens
from tests.fakes import FakeProvider, ok


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, sec: float) -> None:
        self.slept.append(sec)
        self.now += sec


def test_under_limit_does_not_wait():
    clock = FakeClock()
    rl = TokenRateLimiter(1000, clock=clock, sleep=clock.sleep)
    assert rl.acquire(400)[1] == 0
    assert rl.acquire(500)[1] == 0
    assert clock.slept == []


def test_over_limit_waits_until_oldest_leaves_window():
    clock = FakeClock()
    rl = TokenRateLimiter(1000, clock=clock, sleep=clock.sleep)
    rl.acquire(800)
    clock.now += 20
    _, waited = rl.acquire(400)
    assert waited == pytest.approx(40)  # first reservation expires 60 s after it was made


def test_settle_replaces_estimate_with_real_count():
    clock = FakeClock()
    rl = TokenRateLimiter(1000, clock=clock, sleep=clock.sleep)
    res, _ = rl.acquire(900)
    rl.settle(res, 100)  # it actually used far fewer tokens
    assert rl.acquire(800)[1] == 0


def test_disabled_and_oversized_requests():
    assert TokenRateLimiter(0).acquire(10**9) == (None, 0.0)
    clock = FakeClock()
    rl = TokenRateLimiter(1000, clock=clock, sleep=clock.sleep)
    assert rl.acquire(5000)[1] == 0  # bigger than the limit but the window is empty: let the provider decide


def test_estimate_tokens():
    assert estimate_tokens([{"role": "user", "content": "x" * 400}]) == 104


def test_llm_client_paces_groq_requests(settings, session_factory, tmp_path):
    (tmp_path / "p.yaml").write_text("id: p\nversion: v1\nsystem: s\nuser: '${t}'\n", encoding="utf-8")
    clock = FakeClock()
    limiter = TokenRateLimiter(1500, clock=clock, sleep=clock.sleep)
    fake = FakeProvider("groq", script=[ok("a", inp=700, out=300), ok("b", inp=700, out=300)])
    client = LLMClient(settings, session_factory, PromptRegistry(tmp_path), load_pricing(),
                       providers={"groq": fake}, sleep=clock.sleep, rate_limiters={"groq": limiter})

    client.complete(task="t", prompt_id="p", variables={"t": "x" * 2000}, max_output_tokens=500)
    client.complete(task="t", prompt_id="p", variables={"t": "x" * 2000}, max_output_tokens=500)

    assert len(clock.slept) == 1 and clock.slept[0] == pytest.approx(60)  # 1000 real + ~1000 estimate > 1500


def test_ollama_is_not_paced_and_gets_no_reasoning_effort(settings, session_factory, tmp_path):
    (tmp_path / "p.yaml").write_text("id: p\nversion: v1\nsystem: s\nuser: u\n", encoding="utf-8")
    fake = FakeProvider("ollama", script=[ok("a")])
    client = LLMClient(settings, session_factory, PromptRegistry(tmp_path), load_pricing(),
                       providers={"ollama": fake}, sleep=lambda _s: pytest.fail("should not wait"))
    client.complete(task="t", prompt_id="p", provider="ollama")
    assert fake.calls[0]["reasoning_effort"] is None
