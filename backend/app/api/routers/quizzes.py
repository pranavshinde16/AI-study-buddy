"""Quiz routes: generate (per lecture), list, get (answers hidden) and submit (grading).
HTTP only; the logic lives in services/quizzes.py (CLAUDE.md rule 6)."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import AppSettings, CurrentUser, DbSession, Grader, QuizGen
from app.models.learning import Quiz
from app.schemas.errors import error_responses
from app.schemas.quizzes import (
    GenerateQuizRequest,
    QuestionOut,
    QuizOut,
    QuizSummaryOut,
    SubmitQuizRequest,
    SubmitQuizResponse,
)
from app.services import quizzes as quiz_service

router = APIRouter(tags=["quizzes"])


def _quiz_out(db, quiz: Quiz) -> QuizOut:
    questions = quiz_service.questions_of(db, quiz.id)
    return QuizOut(
        quiz_id=quiz.id,
        lecture_id=quiz.lecture_id,
        difficulty=quiz.difficulty,
        created_at=quiz.created_at,
        questions=[
            QuestionOut(id=quiz_service.public_id(q), type=q.type, difficulty=q.difficulty, topic=q.topic,
                        question=q.question, options=q.options_json)
            for q in questions
        ],
        attempts=quiz_service.attempt_count(db, quiz.id),
        meta=(quiz.config_json or {}).get("meta", {}),
    )


@router.post(
    "/lectures/{lecture_id}/generate-quiz",
    response_model=QuizOut,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a quiz from the lecture (answers are hidden until you submit)",
    description=(
        "Writes `num_questions` questions of the requested `types` and `difficulty` from the transcript, "
        "topic by topic (needs the summary/notes from POST /summarize). Every question is validated "
        "(4 unique MCQ options with the answer among them, a real transcript segment, no duplicates); "
        "invalid ones are regenerated. Each call creates a new quiz."
    ),
    responses=error_responses(401, 404, 409, 422, 429, 502, 503),
)
def generate_quiz(
    lecture_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    generator: QuizGen,
    body: GenerateQuizRequest | None = None,
) -> QuizOut:
    req = body or GenerateQuizRequest()
    quiz = quiz_service.generate_quiz(
        db, user, lecture_id,
        num_questions=req.num_questions, types=list(req.types), difficulty=req.difficulty,
        topics=req.topics, adaptive=req.adaptive, settings=settings, generator=generator,
    )
    return _quiz_out(db, quiz)


@router.get(
    "/lectures/{lecture_id}/quizzes",
    response_model=list[QuizSummaryOut],
    summary="Your quizzes for this lecture, newest first",
    responses=error_responses(401, 404),
)
def list_quizzes(lecture_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[QuizSummaryOut]:
    return [QuizSummaryOut(**q) for q in quiz_service.list_quizzes(db, user, lecture_id)]


@router.get(
    "/quizzes/{quiz_id}",
    response_model=QuizOut,
    summary="A quiz without its answers",
    responses=error_responses(401, 404),
)
def get_quiz(quiz_id: uuid.UUID, user: CurrentUser, db: DbSession) -> QuizOut:
    return _quiz_out(db, quiz_service.get_quiz(db, user, quiz_id))


@router.post(
    "/quizzes/{quiz_id}/submit",
    response_model=SubmitQuizResponse,
    summary="Grade your answers, return explanations and update topic mastery",
    description=(
        "MCQ and true/false are graded by rule. Short answers are graded by the LLM against the reference "
        "answer and key points; if that fails, by embedding similarity (`graded_by` says which). "
        "Each submission is stored as a new attempt."
    ),
    responses=error_responses(401, 404, 422, 503),
)
def submit_quiz(
    quiz_id: uuid.UUID,
    body: SubmitQuizRequest,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    grader: Grader,
) -> SubmitQuizResponse:
    return SubmitQuizResponse(
        **quiz_service.submit_quiz(db, user, quiz_id, body.answers, settings=settings, grader=grader)
    )
