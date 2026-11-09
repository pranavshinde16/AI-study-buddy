"""scripts/export_llmops.py renders the markdown from the database (no handwritten numbers)."""

from datetime import UTC, datetime

from app.models.llmops import LLMCall
from app.services.llm.model_info import OllamaModelInfo
from app.services.llm.pricing import load_pricing
from app.services.llm.prompts import PromptRegistry
from app.services.llmops import LlmOpsMetrics, MetricFilter
from app.services.model_registry import ModelRegistryService
from scripts.export_llmops import build, fmt


def test_fmt():
    assert fmt(None) == "n/a" and fmt(0.5) == "0.5" and fmt(0.0) == "0" and fmt(1234.56) == "1,234.6"
    assert fmt(True) == "yes" and fmt("a|b") == "a\\|b"


def test_export_builds_from_rows(db, settings, generator_registry):
    db.add(LLMCall(task="summary", provider="groq", model="openai/gpt-oss-120b", model_version="openai/gpt-oss-120b",
                   status="ok", attempt=1, input_tokens=1234, output_tokens=56, latency_ms=987.0, cost_usd=0.0,
                   prompt_id="summary", prompt_version="summary@v1", ts=datetime(2026, 11, 8, tzinfo=UTC)))
    db.commit()
    registry = ModelRegistryService(settings, generator_registry, PromptRegistry(),
                                    OllamaModelInfo("http://x/v1", fetch=lambda: {"models": []}))
    text = build(db, LlmOpsMetrics(db, load_pricing(), generator_registry), registry, MetricFilter(),
                 datetime(2026, 11, 9, tzinfo=UTC))
    assert text.startswith("# LLMOps results (generated)")
    assert "| summary | groq | openai/gpt-oss-120b | 1 | 987.0 | 987.0 |" in text
    assert "1,234 / 56" in text and "summary@v1" in text
    assert "No golden-set evaluation has been run yet" in text
