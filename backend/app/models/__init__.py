"""Import every model here so `Base.metadata` knows all tables (Alembic autogenerate relies on it)."""

from app.models.chat import ChatMessage, ChatSession, QALog
from app.models.learning import AttemptAnswer, Flashcard, Quiz, QuizAttempt, QuizQuestion, TopicMastery
from app.models.lecture import Chunk, Lecture, LectureOutput, LectureStatus, OutputKind, TranscriptSegment
from app.models.llmops import EvalItem, EvalRun, LLMCall, PipelineRun
from app.models.user import User

__all__ = [
    "AttemptAnswer",
    "ChatMessage",
    "ChatSession",
    "Chunk",
    "EvalItem",
    "EvalRun",
    "Flashcard",
    "LLMCall",
    "Lecture",
    "LectureOutput",
    "LectureStatus",
    "OutputKind",
    "PipelineRun",
    "QALog",
    "Quiz",
    "QuizAttempt",
    "QuizQuestion",
    "TopicMastery",
    "TranscriptSegment",
    "User",
]
