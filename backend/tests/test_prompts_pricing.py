from pathlib import Path

import pytest

from app.services.llm.pricing import load_pricing
from app.services.llm.prompts import PROMPTS_DIR, PromptRegistry


def test_shipped_prompts_load_and_have_versions():
    registry = PromptRegistry(PROMPTS_DIR)
    assert "smoke_test" in registry.ids()
    for pid in registry.ids():
        p = registry.get(pid)
        assert p.version and p.tag == f"{p.id}@{p.version}"


def test_prompt_id_must_match_file_name(tmp_path: Path):
    (tmp_path / "summary.yaml").write_text("id: notes\nversion: v1\nsystem: s\nuser: u\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must match its file name"):
        PromptRegistry(tmp_path)


def test_prompt_requires_version(tmp_path: Path):
    (tmp_path / "x.yaml").write_text("id: x\nsystem: s\nuser: u\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        PromptRegistry(tmp_path)


def test_unknown_prompt_lists_known_ids():
    with pytest.raises(KeyError, match="smoke_test"):
        PromptRegistry(PROMPTS_DIR).get("nope")


def test_shipped_pricing_file_is_free_tier_for_groq():
    pricing = load_pricing()
    assert pricing.providers["groq"].billing == "free_tier"
    assert pricing.cost("groq", "openai/gpt-oss-120b", 10_000, 2_000) == 0.0
    assert pricing.cost("ollama", "anything", 10, 10) == 0.0
    assert pricing.cost("openai", "gpt-5-mini", 1_000_000, 0) == pytest.approx(0.25)
    assert pricing.cost("openai", "unlisted-model", 10, 10) is None
    assert pricing.cost("unknown-provider", "m", 10, 10) is None
