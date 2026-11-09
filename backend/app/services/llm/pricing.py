"""Cost calculation from real token counts and `config/pricing.yaml` (IMPLEMENTATION_PLAN §7.1).

Billing modes per provider:
  free_tier / local -> cost_usd = 0.0   (Groq free plan, Ollama on your laptop)
  paid              -> tokens x price per 1M tokens (ASR: audio minutes x price per minute)
A model missing from the file gives cost_usd = None (unknown), never a guess.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

PRICING_FILE = Path(__file__).resolve().parents[3] / "config" / "pricing.yaml"


class ModelPrice(BaseModel):
    input: float  # USD per 1M input tokens
    output: float  # USD per 1M output tokens


class ProviderPricing(BaseModel):
    billing: Literal["free_tier", "paid", "local"]
    models: dict[str, ModelPrice] = {}
    audio_models: dict[str, float] = {}  # ASR: USD per audio minute


class PricingTable(BaseModel):
    checked: str
    currency: str = "USD"
    providers: dict[str, ProviderPricing]

    def cost(self, provider: str, model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
        p = self.providers.get(provider)
        if p is None:
            return None
        if p.billing in ("free_tier", "local"):
            return 0.0
        price = p.models.get(model)
        if price is None or input_tokens is None or output_tokens is None:
            return None
        return round((input_tokens * price.input + output_tokens * price.output) / 1_000_000, 8)

    def equivalent_cost(self, provider: str, model: str, input_tokens: int | None,
                        output_tokens: int | None) -> float | None:
        """What the call WOULD cost at the provider's listed paid prices (Phase 11, metric M5).

        free_tier -> priced with the reference prices in the file (actual cost stays 0)
        local     -> 0.0 (your own machine)
        paid      -> same as cost()
        None when the model has no listed price or the token counts are missing (never a guess).
        """
        p = self.providers.get(provider)
        if p is None:
            return None
        if p.billing == "local":
            return 0.0
        price = p.models.get(model)
        if price is None or input_tokens is None or output_tokens is None:
            return None
        return round((input_tokens * price.input + output_tokens * price.output) / 1_000_000, 8)

    def equivalent_audio_cost(self, provider: str, model: str, audio_sec: float | None) -> float | None:
        p = self.providers.get(provider)
        if p is None:
            return None
        if p.billing == "local":
            return 0.0
        per_min = p.audio_models.get(model)
        if per_min is None or audio_sec is None:
            return None
        return round(audio_sec / 60.0 * per_min, 8)

    def audio_cost(self, provider: str, model: str, audio_sec: float | None) -> float | None:
        """Speech-to-text cost from the real audio length; None when unknown."""
        p = self.providers.get(provider)
        if p is None:
            return None
        if p.billing in ("free_tier", "local"):
            return 0.0
        per_min = p.audio_models.get(model)
        if per_min is None or audio_sec is None:
            return None
        return round(audio_sec / 60.0 * per_min, 8)


def load_pricing(path: Path = PRICING_FILE) -> PricingTable:
    return PricingTable.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_pricing() -> PricingTable:
    return load_pricing()
