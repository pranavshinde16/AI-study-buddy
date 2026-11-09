"""LLM-as-judge for the eval harness (metric M7 + answer correctness).

All calls go through the shared LLMClient (logged in llm_calls as eval_judge_* tasks, paced for
Groq's free tier, retried on the SAME provider only). The judge is EVAL_JUDGE_PROVIDER /
EVAL_JUDGE_MODEL, chosen to differ from the cloud generator (LLM_MODEL). Known limitation: an
LLM judge can still be biased (towards fluent answers, or towards its own model family when the
judge and the generator are related) and is not a substitute for a human check of a sample.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from app.core.config import Settings
from app.services.llm.client import LLMClient

FAITHFULNESS_TASK = "eval_judge_faithfulness"
CORRECTNESS_TASK = "eval_judge_correctness"


class Claim(BaseModel):
    claim: str
    supported: bool
    evidence: list[str] = Field(default_factory=list, description='excerpt ids, e.g. ["C1"]')


class FaithfulnessOut(BaseModel):
    claims: list[Claim] = Field(default_factory=list)


class CorrectnessOut(BaseModel):
    score: float = Field(description="1, 0.5 or 0")
    reason: str = ""

    @field_validator("score")
    @classmethod
    def _allowed(cls, v: float) -> float:
        if v not in (0, 0.5, 1):
            raise ValueError("score must be 0, 0.5 or 1")
        return float(v)


@dataclass
class FaithfulnessVerdict:
    claims: list[dict]
    supported: int
    total: int
    faithfulness: float | None  # None when the answer has no factual claim
    prompt_version: str
    model_version: str | None
    tokens: int = 0


@dataclass
class CorrectnessVerdict:
    score: float
    reason: str
    prompt_version: str
    model_version: str | None
    tokens: int = 0


@dataclass
class JudgeStats:
    calls: int = 0
    tokens: int = 0
    errors: list[str] = field(default_factory=list)


class Judge:
    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self.settings = settings
        self.llm = llm
        self.provider = settings.eval_judge_provider
        self.model = settings.eval_judge_model
        self.stats = JudgeStats()

    def _complete(self, task: str, prompt_id: str, variables: dict, schema: type[BaseModel]):
        r = self.llm.complete(task=task, prompt_id=prompt_id, variables=variables, schema=schema,
                              provider=self.provider, model=self.model, temperature=0.0)
        self.stats.calls += len(r.call_ids)
        self.stats.tokens += r.input_tokens + r.output_tokens
        return r

    def faithfulness(self, *, question: str, answer: str, chunks: Sequence[tuple[str, str]]) -> FaithfulnessVerdict:
        """chunks: (label, text) exactly as the answering model saw them."""
        context = "\n\n".join(f"[{label}] {text}" for label, text in chunks)
        r = self._complete(FAITHFULNESS_TASK, "eval_faithfulness",
                           {"chunks": context, "question": question, "answer": answer}, FaithfulnessOut)
        out: FaithfulnessOut = r.data  # type: ignore[assignment]
        total = len(out.claims)
        supported = sum(c.supported for c in out.claims)
        return FaithfulnessVerdict(
            claims=[c.model_dump() for c in out.claims], supported=supported, total=total,
            faithfulness=round(supported / total, 4) if total else None,
            prompt_version=r.prompt_version, model_version=r.model_version,
            tokens=r.input_tokens + r.output_tokens,
        )

    def correctness(self, *, question: str, answer: str, reference: str) -> CorrectnessVerdict:
        r = self._complete(CORRECTNESS_TASK, "eval_correctness",
                           {"question": question, "reference": reference, "answer": answer}, CorrectnessOut)
        out: CorrectnessOut = r.data  # type: ignore[assignment]
        return CorrectnessVerdict(score=out.score, reason=out.reason, prompt_version=r.prompt_version,
                                  model_version=r.model_version, tokens=r.input_tokens + r.output_tokens)
