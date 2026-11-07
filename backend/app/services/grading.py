"""Answer grading for quizzes (IMPLEMENTATION_PLAN §6 /submit, Phase 6).

    mcq / true_false -> rule: compared with the stored answer         (graded_by = "rule")
    short_answer     -> the LLM grades every short answer in ONE request against the reference
                        answer and key points (JUDGE_MODEL)             (graded_by = "llm")
                     -> if that request fails (rate limit, outage, invalid JSON twice) or skips
                        an item: cosine similarity of the answer and the reference answer using
                        the local embedding model; >= SHORT_ANSWER_SIM_THRESHOLD is correct
                                                                        (graded_by = "embedding")
    empty answer     -> incorrect without any model call               (graded_by = "rule")

The fallback never switches to another (paid) LLM provider (CLAUDE.md rule 12).
"""

import json
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import structlog
from fastapi import status
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import AppError
from app.services.embeddings import EmbeddingClient, cosine
from app.services.llm.client import LLMClient
from app.services.llm.errors import LLMError

log = structlog.get_logger(__name__)

LETTERS = "ABCD"


class GradingUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "GRADING_UNAVAILABLE"


@dataclass
class Grade:
    correct: bool
    score: float  # 0..1
    graded_by: str  # rule | llm | embedding
    feedback: str | None = None


@dataclass
class ShortItem:
    id: str
    question: str
    reference: str
    key_points: list[str]
    response: str


class GradeItem(BaseModel):
    id: str
    score: float = Field(ge=0.0, le=1.0)
    correct: bool
    feedback: str = ""


class GradesOut(BaseModel):
    grades: list[GradeItem]


# ---------------------------------------------------------------------------- rule grading


def normalise_choice(response: Any, options: list[str]) -> str | None:
    """An MCQ response as a letter: accepts "B", "b", "B)" or the exact option text."""
    if not isinstance(response, str):
        return None
    r = response.strip().rstrip(").:").lstrip("(").strip()
    if len(r) == 1 and r.upper() in LETTERS[: len(options)]:
        return r.upper()
    for i, opt in enumerate(options):
        if opt.strip().casefold() == response.strip().casefold():
            return LETTERS[i]
    return None


def normalise_bool(response: Any) -> bool | None:
    if isinstance(response, bool):
        return response
    if isinstance(response, str) and response.strip().lower() in ("true", "false"):
        return response.strip().lower() == "true"
    return None


def grade_mcq(response: Any, answer: str, options: list[str]) -> Grade:
    choice = normalise_choice(response, options)
    ok = choice == answer
    return Grade(ok, 1.0 if ok else 0.0, "rule")


def grade_true_false(response: Any, answer: bool) -> Grade:
    ok = normalise_bool(response) is answer
    return Grade(ok, 1.0 if ok else 0.0, "rule")


# ---------------------------------------------------------------------------- short answers


class ShortAnswerGrader:
    def __init__(self, settings: Settings, llm: LLMClient, embeddings: EmbeddingClient) -> None:
        self.settings = settings
        self.llm = llm
        self.embeddings = embeddings

    def grade(
        self, items: list[ShortItem], *, lecture_id: uuid.UUID | None, user_id: uuid.UUID | None
    ) -> dict[str, Grade]:
        out: dict[str, Grade] = {}
        todo = []
        for it in items:
            if not it.response.strip():
                out[it.id] = Grade(False, 0.0, "rule", "No answer given.")
            else:
                todo.append(it)
        if not todo:
            return out

        try:
            out.update(self._grade_llm(todo, lecture_id, user_id))
        except LLMError as exc:
            log.warning("short_answer_llm_grading_failed", code=exc.code, items=len(todo))
        missing = [it for it in todo if it.id not in out]
        if missing:
            out.update(self._grade_embedding(missing, lecture_id, user_id))
        return out

    def _grade_llm(self, items: list[ShortItem], lecture_id, user_id) -> dict[str, Grade]:
        payload = [
            {"id": it.id, "question": it.question, "reference_answer": it.reference,
             "key_points": it.key_points, "student_answer": it.response[:2000]}
            for it in items
        ]
        r = self.llm.complete(
            task="grading",
            prompt_id="grade_short",
            schema=GradesOut,
            model=self.settings.judge_model,
            variables={"items": json.dumps(payload, ensure_ascii=False, indent=1)},
            lecture_id=lecture_id,
            user_id=user_id,
        )
        wanted = {it.id for it in items}
        grades: dict[str, Grade] = {}
        for g in r.data.grades:  # type: ignore[union-attr]
            if g.id in wanted and g.id not in grades:
                grades[g.id] = Grade(bool(g.correct), round(float(g.score), 3), "llm", g.feedback.strip() or None)
        return grades

    def _grade_embedding(self, items: list[ShortItem], lecture_id, user_id) -> dict[str, Grade]:
        texts = [it.response for it in items] + [it.reference for it in items]
        try:
            vectors = self.embeddings.embed(texts, task="grading_embedding", lecture_id=lecture_id, user_id=user_id)
        except AppError as exc:
            raise GradingUnavailableError(
                "Short answers could not be graded: the AI grader and the embedding fallback both failed. "
                "Try submitting again in a minute.",
                details={"reason": exc.code},
            ) from exc
        n = len(items)
        threshold = self.settings.short_answer_sim_threshold
        grades: dict[str, Grade] = {}
        for i, it in enumerate(items):
            sim = max(0.0, min(1.0, cosine(vectors[i], vectors[n + i])))
            ok = sim >= threshold
            grades[it.id] = Grade(
                ok,
                round(sim, 3),
                "embedding",
                ("Close in meaning to the reference answer." if ok else "Not close enough in meaning to the reference answer.")
                + " (Graded by similarity because the AI grader was unavailable.)",
            )
        return grades


@lru_cache
def get_short_answer_grader() -> ShortAnswerGrader:
    from app.core.config import get_settings
    from app.services.embeddings import get_embedding_client
    from app.services.llm.client import get_llm_client

    return ShortAnswerGrader(get_settings(), get_llm_client(), get_embedding_client())
