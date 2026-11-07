"""Answer generators for /ask and /chat: a registry of name -> (LLM client, provider, model).

Built in (all three use the same RAG prompt and the same logged LLM client):

    cloud      LLM_PROVIDER / LLM_MODEL          (Groq gpt-oss-120b, free tier, by default)
    finetuned  ollama / FINETUNED_MODEL_TAG      (the SciQ fine-tuned SLM, Phase 10)
    base       ollama / BASE_SLM_MODEL_TAG       (the same SLM before fine-tuning)

More can be added WITHOUT code changes through the ANSWER_GENERATORS setting (JSON), e.g.

    ANSWER_GENERATORS={"small": {"provider": "groq", "model": "openai/gpt-oss-20b"}}

A configured name equal to a built-in one replaces it. Ollama generators default to 0 retries:
if Ollama isn't running, the 503 MODEL_UNAVAILABLE comes back at once instead of after backoff.
The registry never substitutes one generator for another (CLAUDE.md rule 12).
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from fastapi import status
from pydantic import BaseModel

from app.core.config import GeneratorConfig, Settings
from app.core.errors import AppError
from app.services.llm.client import LLMClient, LLMResult

BUILT_IN = ("cloud", "finetuned", "base")


class UnknownGeneratorError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "UNKNOWN_GENERATOR"


@dataclass(frozen=True)
class AnswerGenerator:
    name: str
    provider: str
    model: str
    max_retries: int | None
    description: str
    llm: LLMClient

    def complete(self, *, schema: type[BaseModel] | None = None, **kwargs: Any) -> LLMResult:
        return self.llm.complete(provider=self.provider, model=self.model, max_retries=self.max_retries,
                                 schema=schema, **kwargs)


def built_in_configs(settings: Settings) -> dict[str, GeneratorConfig]:
    return {
        "cloud": GeneratorConfig(provider=settings.llm_provider, model=settings.llm_model,
                                 description=f"Cloud LLM ({settings.llm_provider})"),
        "finetuned": GeneratorConfig(provider="ollama", model=settings.finetuned_model_tag, max_retries=0,
                                     description="Fine-tuned small language model (Ollama, Phase 10)"),
        "base": GeneratorConfig(provider="ollama", model=settings.base_slm_model_tag, max_retries=0,
                                description="Base small language model before fine-tuning (Ollama)"),
    }


class GeneratorRegistry:
    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        configs = {**built_in_configs(settings), **settings.answer_generators}
        self._generators = {
            name: AnswerGenerator(
                name=name,
                provider=c.provider,
                model=c.model,
                max_retries=c.max_retries if c.max_retries is not None else (0 if c.provider == "ollama" else None),
                description=c.description or f"{c.provider} / {c.model}",
                llm=llm,
            )
            for name, c in configs.items()
        }

    def names(self) -> list[str]:
        return list(self._generators)

    def all(self) -> list[AnswerGenerator]:
        return list(self._generators.values())

    def get(self, name: str) -> AnswerGenerator:
        try:
            return self._generators[name]
        except KeyError:
            raise UnknownGeneratorError(
                f"Unknown answer generator '{name}'.", details={"available": self.names()}
            ) from None


@lru_cache
def get_generator_registry() -> GeneratorRegistry:
    from app.core.config import get_settings
    from app.services.llm.client import get_llm_client

    return GeneratorRegistry(get_settings(), get_llm_client())
