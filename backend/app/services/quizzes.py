"""Quiz use cases: generate, read (answers hidden), list, submit (grade + mastery).

Routers call these; no HTTP details here (CLAUDE.md rule 6). Every read is owner-scoped:
another user's quiz id gives 404.

Mastery (topic_mastery, one row per user + lecture + topic) is an exponential moving average
of the user's results on that topic:

    first attempt : mastery = result
    later         : mastery = alpha * result + (1 - alpha) * mastery      (alpha = MASTERY_EMA_ALPHA)

where `result` is the mean score (0..1) of that topic's questions in the submitted attempt.
"""

import uuid
from collections import defaultdict
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.models.learning import AttemptAnswer, Quiz, QuizAttempt, QuizQuestion, TopicMastery
from app.models.lecture import Lecture, LectureStatus, OutputKind, TranscriptSegment
from app.models.user import User
from app.services.generation.context import TopicSpan, filter_topics, topics_from_notes
from app.services.generation.quiz import QuizGenerator
from app.services.grading import (
    Grade,
    ShortAnswerGrader,
    ShortItem,
    grade_mcq,
    grade_true_false,
    normalise_bool,
)
from app.services.lectures import TRANSCRIPT_READY, LectureNotReadyError, get_lecture
from app.services.summaries import GenerationInProgressError, NotesNotGeneratedError, load_outputs


class QuizValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_ERROR"


class AdaptiveNotAvailableError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "ADAPTIVE_NOT_AVAILABLE"


def public_id(q: QuizQuestion) -> str:
    return f"q{q.idx + 1}"


# ---------------------------------------------------------------------------- lecture context


def lecture_context(db: Session, user: User, lecture_id: uuid.UUID) -> tuple[Lecture, list[TopicSpan], list[TranscriptSegment], dict[str, Any]]:
    """The lecture, its topics (from the notes), its segments and its cached outputs.
    Quizzes and flashcards need the Phase 5 notes, because questions are tagged by topic."""
    lecture = get_lecture(db, user, lecture_id)
    if lecture.status not in TRANSCRIPT_READY:
        raise LectureNotReadyError(
            "The transcript is not ready yet", details={"status": lecture.status, "progress": lecture.progress}
        )
    outputs = load_outputs(db, lecture_id)
    notes = outputs.get(OutputKind.NOTES)
    if notes is None:
        if lecture.status == LectureStatus.GENERATING:
            raise GenerationInProgressError("Topic notes are being generated; poll /status and try again when ready")
        raise NotesNotGeneratedError(
            f"Generate the summary and topic notes first: POST /api/lectures/{lecture_id}/summarize",
            details={"status": lecture.status},
        )
    topics = topics_from_notes(notes.content_json)
    segments = list(
        db.scalars(
            select(TranscriptSegment).where(TranscriptSegment.lecture_id == lecture_id).order_by(TranscriptSegment.idx)
        )
    )
    return lecture, topics, segments, {k: v.content_json for k, v in outputs.items()}


# ---------------------------------------------------------------------------- generate / read


def generate_quiz(
    db: Session,
    user: User,
    lecture_id: uuid.UUID,
    *,
    num_questions: int,
    types: list[str],
    difficulty: str,
    topics: list[str] | None,
    adaptive: bool,
    settings: Settings,
    generator: QuizGenerator,
) -> Quiz:
    if adaptive:
        raise AdaptiveNotAvailableError("Adaptive quizzes arrive in Phase 9; send adaptive=false for now.")
    if num_questions > settings.quiz_max_questions:
        raise QuizValidationError(
            f"num_questions must be at most {settings.quiz_max_questions}",
            details={"max": settings.quiz_max_questions},
        )
    lecture, all_topics, segments, _ = lecture_context(db, user, lecture_id)
    chosen, unknown = filter_topics(all_topics, topics)
    if unknown:
        raise QuizValidationError(
            "Unknown topic(s); use titles from GET /notes",
            details={"unknown": unknown, "available": [t.title for t in all_topics]},
        )

    draft = generator.generate(
        lecture_id=lecture.id,
        user_id=user.id,
        title=lecture.title,
        topics=chosen,
        segments=segments,
        num_questions=num_questions,
        types=types,
        difficulty=difficulty,
    )
    config = {"num_questions": num_questions, "types": types, "difficulty": difficulty,
              "topics": topics, "adaptive": adaptive}
    quiz = Quiz(
        lecture_id=lecture.id,
        user_id=user.id,
        difficulty=difficulty,
        config_json={"request": config, "meta": draft.meta},
        prompt_version=draft.prompt_version,
        model=draft.model,
    )
    db.add(quiz)
    db.flush()
    db.add_all(
        QuizQuestion(
            quiz_id=quiz.id,
            idx=i,
            type=q.type,
            difficulty=q.difficulty,
            topic=q.topic,
            question=q.question,
            options_json=q.options,
            answer=q.answer,
            rubric_json=q.key_points,
            explanation=q.explanation,
            source_start=q.source_start,
        )
        for i, q in enumerate(draft.questions)
    )
    try:
        db.commit()
    except IntegrityError:  # the lecture was deleted while the questions were being written
        db.rollback()
        raise NotFoundError("Lecture not found", code="LECTURE_NOT_FOUND") from None
    db.refresh(quiz)
    return quiz


def get_quiz(db: Session, user: User, quiz_id: uuid.UUID) -> Quiz:
    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.user_id == user.id))
    if quiz is None:
        raise NotFoundError("Quiz not found", code="QUIZ_NOT_FOUND")
    return quiz


def questions_of(db: Session, quiz_id: uuid.UUID) -> list[QuizQuestion]:
    return list(db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id).order_by(QuizQuestion.idx)))


def attempt_count(db: Session, quiz_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(QuizAttempt).where(QuizAttempt.quiz_id == quiz_id)) or 0


def list_quizzes(db: Session, user: User, lecture_id: uuid.UUID) -> list[dict[str, Any]]:
    get_lecture(db, user, lecture_id)
    quizzes = db.scalars(
        select(Quiz).where(Quiz.lecture_id == lecture_id, Quiz.user_id == user.id).order_by(Quiz.created_at.desc())
    ).all()
    out = []
    for q in quizzes:
        n = db.scalar(select(func.count()).select_from(QuizQuestion).where(QuizQuestion.quiz_id == q.id)) or 0
        attempts, best = db.execute(
            select(func.count(QuizAttempt.id), func.max(QuizAttempt.percent)).where(QuizAttempt.quiz_id == q.id)
        ).one()
        out.append({"quiz_id": q.id, "difficulty": q.difficulty, "num_questions": n, "created_at": q.created_at,
                    "attempts": attempts or 0, "best_percent": best})
    return out


# ---------------------------------------------------------------------------- submit


def suggested_difficulty(percent: float) -> str:
    """Same thresholds the adaptive quiz uses for mastery (Phase 9): <50% easy, 50-80% medium, >80% hard."""
    if percent < 50:
        return "easy"
    if percent <= 80:
        return "medium"
    return "hard"


def _check_answers(questions: list[QuizQuestion], answers: dict[str, Any]) -> None:
    by_id = {public_id(q): q for q in questions}
    unknown = sorted(set(answers) - set(by_id))
    if unknown:
        raise QuizValidationError("Unknown question id(s)", details={"unknown": unknown, "valid": list(by_id)})
    bad = []
    for qid, value in answers.items():
        q = by_id[qid]
        if value is None:
            continue
        if q.type == "true_false" and normalise_bool(value) is None:
            bad.append({"id": qid, "expected": "true or false"})
        elif q.type in ("mcq", "short_answer") and not isinstance(value, str):
            bad.append({"id": qid, "expected": "a letter A-D or the option text" if q.type == "mcq" else "text"})
    if bad:
        raise QuizValidationError("Invalid answer type(s)", details={"invalid": bad})


def update_mastery(
    db: Session, user_id: uuid.UUID, lecture_id: uuid.UUID, results: dict[str, list[float]], alpha: float
) -> dict[str, float]:
    """Apply one attempt's per-topic results to topic_mastery; returns the new values."""
    out: dict[str, float] = {}
    for topic, scores in results.items():
        value = sum(scores) / len(scores)
        row = db.scalar(
            select(TopicMastery).where(
                TopicMastery.user_id == user_id, TopicMastery.lecture_id == lecture_id, TopicMastery.topic == topic
            )
        )
        if row is None:
            row = TopicMastery(user_id=user_id, lecture_id=lecture_id, topic=topic, score_ema=value, attempts=len(scores))
            db.add(row)
        else:
            row.score_ema = alpha * value + (1 - alpha) * row.score_ema
            row.attempts += len(scores)
        out[topic] = round(row.score_ema, 4)
    return out


def submit_quiz(
    db: Session,
    user: User,
    quiz_id: uuid.UUID,
    answers: dict[str, Any],
    *,
    settings: Settings,
    grader: ShortAnswerGrader,
) -> dict[str, Any]:
    quiz = get_quiz(db, user, quiz_id)
    questions = questions_of(db, quiz.id)
    _check_answers(questions, answers)

    grades: dict[str, Grade] = {}
    short: list[ShortItem] = []
    for q in questions:
        qid, response = public_id(q), answers.get(public_id(q))
        if response is None or (isinstance(response, str) and not response.strip()):
            grades[qid] = Grade(False, 0.0, "rule", "No answer given.")
        elif q.type == "mcq":
            grades[qid] = grade_mcq(response, q.answer, q.options_json or [])
        elif q.type == "true_false":
            grades[qid] = grade_true_false(response, bool(q.answer))
        else:
            short.append(ShortItem(qid, q.question, str(q.answer), list(q.rubric_json or []), str(response)))
    if short:
        grades.update(grader.grade(short, lecture_id=quiz.lecture_id, user_id=user.id))

    correct = sum(1 for g in grades.values() if g.correct)
    total = len(questions)
    percent = round(100.0 * correct / total, 1) if total else 0.0
    attempt = QuizAttempt(quiz_id=quiz.id, user_id=user.id, score=float(correct), total=total, percent=percent)
    db.add(attempt)
    db.flush()

    per_topic: dict[str, list[float]] = defaultdict(list)
    per_topic_correct: dict[str, float] = defaultdict(float)
    results = []
    for q in questions:
        qid = public_id(q)
        g = grades[qid]
        response = answers.get(qid)
        db.add(AttemptAnswer(attempt_id=attempt.id, question_id=q.id, response=response, correct=g.correct,
                             score=g.score, graded_by=g.graded_by, feedback=g.feedback))
        topic = q.topic or "General"
        per_topic[topic].append(g.score)
        per_topic_correct[topic] += 1.0 if g.correct else 0.0
        results.append({
            "id": qid, "type": q.type, "topic": q.topic, "question": q.question, "your_answer": response,
            "correct": g.correct, "score": g.score, "correct_answer": q.answer, "explanation": q.explanation,
            "timestamp": q.source_start, "graded_by": g.graded_by, "feedback": g.feedback,
        })

    mastery = update_mastery(db, user.id, quiz.lecture_id, per_topic, settings.mastery_ema_alpha)
    try:
        db.commit()
    except IntegrityError:  # the quiz or lecture was deleted while grading
        db.rollback()
        raise NotFoundError("Quiz not found", code="QUIZ_NOT_FOUND") from None

    topics = [
        {"topic": t, "correct": per_topic_correct[t], "total": len(s), "mastery": mastery[t]}
        for t, s in per_topic.items()
    ]
    weak = sorted((t for t, m in mastery.items() if m < settings.mastery_weak_threshold), key=lambda t: mastery[t])
    return {
        "attempt_id": attempt.id, "quiz_id": quiz.id, "score": float(correct), "total": total, "percent": percent,
        "results": results, "topics": topics, "weak_topics": weak,
        "suggested_next_difficulty": suggested_difficulty(percent),
    }
