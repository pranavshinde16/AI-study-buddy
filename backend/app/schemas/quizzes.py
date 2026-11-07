"""Shapes for quiz generation, retrieval and submission (IMPLEMENTATION_PLAN §6).

Answers are never included in a quiz until it is submitted. Question ids are "q1", "q2", ...
in quiz order. Timestamps (`timestamp`) are seconds from the start of the lecture, taken from
the transcript segment that supports the question.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

QuestionType = Literal["mcq", "true_false", "short_answer"]
DifficultyIn = Literal["easy", "medium", "hard", "mixed"]


class GenerateQuizRequest(BaseModel):
    num_questions: int = Field(10, ge=1, description="1 to QUIZ_MAX_QUESTIONS (default limit 20)")
    types: list[QuestionType] = Field(default_factory=lambda: ["mcq", "true_false", "short_answer"], min_length=1)
    difficulty: DifficultyIn = Field("medium", description='easy | medium | hard | mixed (cycles all three)')
    topics: list[str] | None = Field(None, description="Topic titles from /notes to focus on; null = all topics")
    adaptive: bool = Field(False, description="Weights topics by mastery; available from Phase 9")

    @field_validator("types")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class QuestionOut(BaseModel):
    id: str = Field(description='"q1", "q2", ... (use these keys when submitting)')
    type: QuestionType
    difficulty: str
    topic: str | None
    question: str
    options: list[str] | None = Field(description="mcq only: 4 options, answer with the letter A-D (or the option text)")


class QuizMeta(BaseModel):
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    requested: int | None = None
    generated: int | None = None
    invalid_items: int | None = Field(None, description="Questions rejected by validation and regenerated")
    invalid_reasons: dict[str, int] = {}
    regeneration_requests: int | None = None
    batches: int | None = None
    llm_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    llm_latency_ms: float | None = None
    generated_at: datetime | None = None


class QuizOut(BaseModel):
    quiz_id: uuid.UUID
    lecture_id: uuid.UUID
    difficulty: str | None
    created_at: datetime
    questions: list[QuestionOut]
    attempts: int = Field(0, description="How many times you have submitted this quiz")
    meta: QuizMeta


class QuizSummaryOut(BaseModel):
    quiz_id: uuid.UUID
    difficulty: str | None
    num_questions: int
    created_at: datetime
    attempts: int
    best_percent: float | None


class SubmitQuizRequest(BaseModel):
    answers: dict[str, bool | str | None] = Field(
        description='{"q1": "B", "q2": true, "q3": "free text"}; unanswered questions count as wrong'
    )


class QuestionResult(BaseModel):
    id: str
    type: QuestionType
    topic: str | None
    question: str
    your_answer: bool | str | None
    correct: bool
    score: float = Field(description="0..1; short answers can get partial credit")
    correct_answer: bool | str = Field(description="mcq: letter; true_false: boolean; short_answer: model answer")
    explanation: str | None
    timestamp: float | None = Field(description="Where the lecture covers this (seconds); from the transcript")
    graded_by: Literal["rule", "llm", "embedding"]
    feedback: str | None = None


class TopicScore(BaseModel):
    topic: str
    correct: float
    total: int
    mastery: float = Field(description="Exponential moving average of your results on this topic (0..1)")


class SubmitQuizResponse(BaseModel):
    attempt_id: uuid.UUID
    quiz_id: uuid.UUID
    score: float = Field(description="Number of correct answers")
    total: int
    percent: float
    results: list[QuestionResult]
    topics: list[TopicScore]
    weak_topics: list[str]
    suggested_next_difficulty: Literal["easy", "medium", "hard"]
