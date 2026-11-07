"""Quiz endpoints: generate (answers hidden), get, list, submit (grading, attempts, topic mastery),
validation errors and ownership. The LLM and embeddings are fakes (no network)."""

import uuid

import pytest
from sqlalchemy import select

from app.models.learning import AttemptAnswer, QuizAttempt, QuizQuestion, TopicMastery
from tests.fakes import rate_limited


def _quiz(client, headers, lid, **body):
    return client.post(f"/api/lectures/{lid}/generate-quiz", headers=headers, json=body)


def _answer_key(db, quiz_id):
    qs = db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == uuid.UUID(quiz_id)).order_by(QuizQuestion.idx))
    return {f"q{q.idx + 1}": q for q in qs}


def _other_user(client, make_user):
    make_user("eve@example.com", "another-password-123", "Eve")
    tok = client.post("/api/auth/login", json={"email": "eve@example.com", "password": "another-password-123"})
    return {"Authorization": f"Bearer {tok.json()['access_token']}"}


def test_generate_quiz_hides_answers(client, auth_headers, make_ready_lecture, db, fake_llm):
    lid = make_ready_lecture()
    r = _quiz(client, auth_headers, lid, num_questions=6, types=["mcq", "true_false", "short_answer"],
              difficulty="mixed")
    assert r.status_code == 201, r.text
    body = r.json()
    assert [q["id"] for q in body["questions"]] == [f"q{i}" for i in range(1, 7)]
    assert [q["difficulty"] for q in body["questions"]] == ["easy", "medium", "hard"] * 2
    for q in body["questions"]:
        assert set(q) == {"id", "type", "difficulty", "topic", "question", "options"}  # no answer / explanation
        assert q["topic"] in {"Topic 0", "Topic 5"}
        if q["type"] == "mcq":
            assert len(q["options"]) == 4 and len(set(q["options"])) == 4
        else:
            assert q["options"] is None
    assert body["meta"]["generated"] == 6 and body["meta"]["prompt_version"] == "quiz@v1"
    assert body["attempts"] == 0

    # the stored questions have valid answers and transcript timestamps
    key = _answer_key(db, body["quiz_id"])
    for q in key.values():
        assert q.source_start is not None and q.source_start % 10 == 0  # a segment start (i * 10 s)
        if q.type == "mcq":
            assert q.answer in "ABCD"

    got = client.get(f"/api/quizzes/{body['quiz_id']}", headers=auth_headers)
    assert got.status_code == 200 and got.json()["questions"] == body["questions"]


def test_quiz_needs_notes(client, auth_headers, make_ready_lecture):
    lid = make_ready_lecture(summarize=False)
    r = _quiz(client, auth_headers, lid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOTES_NOT_GENERATED"


def test_quiz_needs_a_transcript(client, auth_headers, make_ready_lecture, db):
    from app.models.lecture import Lecture

    lid = make_ready_lecture(summarize=False)
    db.get(Lecture, lid).status = "transcribing"
    db.commit()
    r = _quiz(client, auth_headers, lid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "LECTURE_NOT_READY"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"num_questions": 21}, "VALIDATION_ERROR"),
        ({"num_questions": 0}, "VALIDATION_ERROR"),
        ({"types": []}, "VALIDATION_ERROR"),
        ({"types": ["essay"]}, "VALIDATION_ERROR"),
        ({"difficulty": "extreme"}, "VALIDATION_ERROR"),
        ({"topics": ["Photosynthesis"]}, "VALIDATION_ERROR"),
        ({"adaptive": True}, "ADAPTIVE_NOT_AVAILABLE"),
    ],
)
def test_generate_quiz_validation(client, auth_headers, make_ready_lecture, body, code):
    lid = make_ready_lecture()
    r = _quiz(client, auth_headers, lid, **body)
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_topic_filter(client, auth_headers, make_ready_lecture):
    lid = make_ready_lecture()
    r = _quiz(client, auth_headers, lid, num_questions=3, topics=["topic 5"], types=["true_false"])
    assert r.status_code == 201, r.text
    assert {q["topic"] for q in r.json()["questions"]} == {"Topic 5"}


def test_rate_limit_returns_429_envelope(client, auth_headers, make_ready_lecture, fake_llm, settings):
    lid = make_ready_lecture()
    settings.llm_max_retries = 0
    fake_llm.fail["quiz"] = rate_limited(retry_after=5)
    r = _quiz(client, auth_headers, lid)
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_submit_grades_explains_and_updates_mastery(client, auth_headers, make_ready_lecture, db, fake_llm, settings):
    lid = make_ready_lecture()
    quiz = _quiz(client, auth_headers, lid, num_questions=3, types=["mcq", "true_false", "short_answer"]).json()
    key = _answer_key(db, quiz["quiz_id"])
    mcq, tf, sa = key["q1"], key["q2"], key["q3"]
    wrong_letter = next(letter for letter in "ABCD" if letter != mcq.answer)

    # all correct (the short answer mentions "energy", which the fake grader accepts)
    answers = {"q1": mcq.answer.lower(), "q2": tf.answer, "q3": "It is about energy."}
    r = client.post(f"/api/quizzes/{quiz['quiz_id']}/submit", headers=auth_headers, json={"answers": answers})
    assert r.status_code == 200, r.text
    res = r.json()
    assert (res["score"], res["total"], res["percent"]) == (3, 3, 100.0)
    assert res["suggested_next_difficulty"] == "hard" and res["weak_topics"] == []
    by_id = {x["id"]: x for x in res["results"]}
    assert by_id["q1"]["graded_by"] == "rule" and by_id["q1"]["correct_answer"] == mcq.answer
    assert by_id["q3"]["graded_by"] == "llm" and by_id["q3"]["feedback"]
    for x in res["results"]:
        assert x["explanation"] and x["timestamp"] is not None

    topics = {t["topic"]: t for t in res["topics"]}
    assert all(t["mastery"] == 1.0 for t in topics.values())
    rows = {m.topic: m for m in db.scalars(select(TopicMastery).where(TopicMastery.lecture_id == lid))}
    assert set(rows) == set(topics) and all(m.score_ema == 1.0 for m in rows.values())

    # second attempt: all wrong -> EMA moves by alpha
    answers = {"q1": wrong_letter, "q2": not tf.answer, "q3": "no idea"}
    res2 = client.post(f"/api/quizzes/{quiz['quiz_id']}/submit", headers=auth_headers, json={"answers": answers}).json()
    assert (res2["score"], res2["percent"]) == (0, 0.0)
    assert res2["suggested_next_difficulty"] == "easy"
    expected = round(settings.mastery_ema_alpha * 0.0 + (1 - settings.mastery_ema_alpha) * 1.0, 4)
    assert all(t["mastery"] == expected for t in res2["topics"])
    assert set(res2["weak_topics"]) == ({t for t in topics} if expected < settings.mastery_weak_threshold else set())
    db.expire_all()
    assert {m.topic: round(m.score_ema, 4) for m in db.scalars(select(TopicMastery))} == {t: expected for t in topics}
    assert sum(m.attempts for m in db.scalars(select(TopicMastery))) == 6  # 3 questions x 2 attempts

    attempts = list(db.scalars(select(QuizAttempt).where(QuizAttempt.quiz_id == uuid.UUID(quiz["quiz_id"]))))
    assert sorted(a.percent for a in attempts) == [0.0, 100.0]
    stored = list(db.scalars(select(AttemptAnswer)))
    assert len(stored) == 6 and {a.graded_by for a in stored} == {"rule", "llm"}

    listed = client.get(f"/api/lectures/{lid}/quizzes", headers=auth_headers).json()
    assert listed[0]["attempts"] == 2 and listed[0]["best_percent"] == 100.0 and listed[0]["num_questions"] == 3
    assert client.get(f"/api/quizzes/{quiz['quiz_id']}", headers=auth_headers).json()["attempts"] == 2


def test_unanswered_questions_count_as_wrong(client, auth_headers, make_ready_lecture, fake_llm):
    lid = make_ready_lecture()
    quiz = _quiz(client, auth_headers, lid, num_questions=2, types=["true_false"]).json()
    res = client.post(f"/api/quizzes/{quiz['quiz_id']}/submit", headers=auth_headers, json={"answers": {}}).json()
    assert res["score"] == 0 and all(x["feedback"] == "No answer given." for x in res["results"])
    assert "grading" not in fake_llm.tasks


@pytest.mark.parametrize(
    ("answers", "detail_key"),
    [({"q9": "A"}, "unknown"), ({"q1": "maybe"}, "invalid")],
)
def test_submit_validation(client, auth_headers, make_ready_lecture, answers, detail_key):
    lid = make_ready_lecture()
    quiz = _quiz(client, auth_headers, lid, num_questions=1, types=["true_false"]).json()
    r = client.post(f"/api/quizzes/{quiz['quiz_id']}/submit", headers=auth_headers, json={"answers": answers})
    assert r.status_code == 422 and detail_key in r.json()["error"]["details"]


def test_submit_with_grader_down_uses_embedding_fallback(client, auth_headers, make_ready_lecture, fake_llm, settings):
    lid = make_ready_lecture()
    quiz = _quiz(client, auth_headers, lid, num_questions=1, types=["short_answer"]).json()
    settings.llm_max_retries = 0
    fake_llm.fail["grading"] = rate_limited()
    res = client.post(f"/api/quizzes/{quiz['quiz_id']}/submit", headers=auth_headers,
                      json={"answers": {"q1": "the reference answer about energy"}}).json()
    assert res["results"][0]["graded_by"] == "embedding" and res["results"][0]["correct"] is True


def test_other_users_cannot_see_or_submit(client, auth_headers, make_ready_lecture, make_user):
    lid = make_ready_lecture()
    quiz = _quiz(client, auth_headers, lid, num_questions=1, types=["true_false"]).json()
    eve = _other_user(client, make_user)
    assert client.get(f"/api/quizzes/{quiz['quiz_id']}", headers=eve).status_code == 404
    r = client.post(f"/api/quizzes/{quiz['quiz_id']}/submit", headers=eve, json={"answers": {}})
    assert r.status_code == 404 and r.json()["error"]["code"] == "QUIZ_NOT_FOUND"
    assert _quiz(client, eve, lid).status_code == 404
    assert client.get(f"/api/lectures/{lid}/quizzes", headers=eve).status_code == 404
    assert client.get(f"/api/quizzes/{quiz['quiz_id']}").status_code == 401


def test_deleting_the_lecture_removes_its_quizzes(client, auth_headers, make_ready_lecture, db):
    lid = make_ready_lecture()
    quiz = _quiz(client, auth_headers, lid, num_questions=1, types=["true_false"]).json()
    assert client.delete(f"/api/lectures/{lid}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/quizzes/{quiz['quiz_id']}", headers=auth_headers).status_code == 404
