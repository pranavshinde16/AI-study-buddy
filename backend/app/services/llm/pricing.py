"""Cost calculation from real token counts and `config/pricing.yaml` (IMPLEMENTATION_PLAN §7.1).

Billing modes per provider:
  free_tier / local -> cost_usd = 0.0   (Groq free plan, Ollama on your laptop)
  paid              -> tokens x price per 1M tokens
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


def load_pricing(path: Path = PRICING_FILE) -> PricingTable:
    return PricingTable.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_pricing() -> PricingTable:
    return load_pricing()
