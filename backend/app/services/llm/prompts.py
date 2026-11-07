"""Versioned prompt registry: loads `app/prompts/*.yaml` (CLAUDE.md rule 5).

Each file holds one prompt:

    id: summary            # must equal the file name (summary.yaml)
    version: v1            # bump whenever the prompt's behaviour changes
    description: ...
    model: null            # optional per-prompt model override
    temperature: null      # optional
    max_output_tokens: null
    system: |
      ...
    user: |
      Transcript:
      ${transcript}

Placeholders use `${name}` (Python string.Template), so literal `{ }` braces such as JSON
examples need no escaping. A missing variable raises `PromptRenderError`.
"""

from functools import lru_cache
from pathlib import Path
from string import Template

import yaml
from pydantic import BaseModel, Field, ValidationError

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class PromptRenderError(ValueError):
    pass


class PromptTemplate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    version: str = Field(min_length=1)
    description: str = ""
    model: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    system: str
    user: str

    @property
    def tag(self) -> str:
        """`id@version`, the value stored in llm_calls.prompt_version (e.g. `summary@v2`)."""
        return f"{self.id}@{self.version}"

    def render(self, variables: dict[str, object]) -> tuple[str, str]:
        values = {k: str(v) for k, v in variables.items()}
        try:
            return Template(self.system).substitute(values), Template(self.user).substitute(values)
        except KeyError as exc:
            raise PromptRenderError(f"Prompt '{self.id}' needs variable {exc.args[0]!r}") from exc
        except ValueError as exc:
            raise PromptRenderError(f"Prompt '{self.id}' has an invalid placeholder: {exc}") from exc


class PromptRegistry:
    def __init__(self, directory: Path = PROMPTS_DIR) -> None:
        self.directory = directory
        self._prompts: dict[str, PromptTemplate] = {}
        for path in sorted(directory.glob("*.yaml")):
            self._load(path)

    def _load(self, path: Path) -> None:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            prompt = PromptTemplate.model_validate(raw)
        except (yaml.YAMLError, ValidationError) as exc:
            raise ValueError(f"Invalid prompt file {path.name}: {exc}") from exc
        if prompt.id != path.stem:
            raise ValueError(f"Prompt id '{prompt.id}' must match its file name '{path.stem}.yaml'")
        self._prompts[prompt.id] = prompt

    def get(self, prompt_id: str) -> PromptTemplate:
        try:
            return self._prompts[prompt_id]
        except KeyError:
            raise KeyError(f"Unknown prompt '{prompt_id}'. Known: {sorted(self._prompts)}") from None

    def ids(self) -> list[str]:
        return sorted(self._prompts)


@lru_cache
def get_prompt_registry() -> PromptRegistry:
    return PromptRegistry()
