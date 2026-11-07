"""Quiz generation without HTTP: slot planning, batching, per-item validation and regeneration
of invalid items. Uses the fake LLM (no network)."""

import random
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.models.llmops import LLMCall
from app.services.generation.context import TopicSpan, allocate, build_batches, filter_topics, topic_of
from app.services.generation.quiz import (
    QuestionItem,
    QuizGenerationError,
    clean_options,
    plan_slots,
    validate_item,
    Slot,
)
from tests.fakes import rate_limited


@dataclass
class Seg:
    idx: int
    start_sec: float
    end_sec: float
    text: str


SEGS = [Seg(i, i * 10.0, i * 10.0 + 9.5, f"sentence {i} about cells and energy") for i in range(20)]
TOPICS = [TopicSpan("Glycolysis", 0, 9), TopicSpan("Krebs cycle", 10, 19)]


# ---------------------------------------------------------------------------- planning


def test_plan_slots_round_robins_types_and_mixed_difficulty():
    assert plan_slots(4, ["mcq", "true_false"], "hard") == [
        ("mcq", "hard"), ("true_false", "hard"), ("mcq", "hard"), ("true_false", "hard"),
    ]
    assert [d for _, d in plan_slots(6, ["mcq"], "mixed")] == ["easy", "medium", "hard"] * 2


@pytest.mark.parametrize(
    ("total", "weights", "expected"),
    [
        (10, [100, 100], [5, 5]),
        (10, [300, 100], [8, 2]),
        (3, [10, 10, 10, 10, 10, 10], [0, 1, 0, 1, 0, 1]),  # fewer items than batches: spread out
        (5, [1, 1000], [1, 4]),  # every batch gets at least one when there are enough items
        (0, [5, 5], [0, 0]),
    ],
)
def test_allocate(total, weights, expected):
    out = allocate(total, weights)
    assert out == expected and sum(out) == total


def test_build_batches_respects_token_cap_and_splits_long_topics():
    one = build_batches(TOPICS, SEGS, max_tokens=10_000)
    assert len(one) == 1 and [t.title for t in one[0].topics] == ["Glycolysis", "Krebs cycle"]

    small = build_batches(TOPICS, SEGS, max_tokens=60)
    assert len(small) > 2
    assert all(b.tokens <= 60 for b in small)
    covered = [s.idx for b in small for s in b.segments]
    assert covered == list(range(20))  # every segment once, in order
    assert all(len(b.topics) == 1 for b in small)  # parts of one topic never mix with the next here


def test_filter_topics_and_topic_of():
    kept, unknown = filter_topics(TOPICS, ["krebs CYCLE", "Photosynthesis"])
    assert [t.title for t in kept] == ["Krebs cycle"] and unknown == ["Photosynthesis"]
    assert filter_topics(TOPICS, None) == (TOPICS, [])
    assert topic_of(TOPICS, 12) == "Krebs cycle" and topic_of(TOPICS, 99) is None


def test_clean_options_strips_labels_only_when_all_four_are_labelled():
    assert clean_options(["A) Paris", "B) Rome", "C) Oslo", "D) Bern"]) == ["Paris", "Rome", "Oslo", "Bern"]
    assert clean_options(["(a) x", "(b) y", "(c) z", "(d) w"]) == ["x", "y", "z", "w"]
    keep = ["D. melanogaster", "E. coli", "Yeast", "Mice"]
    assert clean_options(keep) == keep


# ---------------------------------------------------------------------------- validation


def _batch():
    return build_batches(TOPICS, SEGS, max_tokens=10_000)[0]


def _item(**kw) -> QuestionItem:
    base = dict(slot=1, type="mcq", question="Which molecule carries energy?", options=["ATP", "DNA", "RNA", "CO2"],
                answer="ATP", explanation="The lecture says ATP carries energy.", segment_id=12)
    base.update(kw)
    return QuestionItem(**base)


def _check(item, slot=Slot(1, "mcq", "easy"), seen=None):
    by_idx = {s.idx: s for s in SEGS}
    return validate_item(item, slot, _batch(), TOPICS, by_idx, seen if seen is not None else set(), random.Random(1))


def test_valid_mcq_gets_shuffled_letter_topic_and_transcript_timestamp():
    q, reason = _check(_item())
    assert reason is None
    assert sorted(q.options) == sorted(["ATP", "DNA", "RNA", "CO2"])
    assert q.options["ABCD".index(q.answer)] == "ATP"
    assert q.topic == "Krebs cycle" and q.source_start == 120.0 and q.segment_id == 12
    assert q.difficulty == "easy"  # from the slot, not the model


@pytest.mark.parametrize("answer", ["B", "b", "B)", "(B)", "B."])
def test_mcq_answer_may_be_a_letter(answer):
    q, reason = _check(_item(answer=answer))
    assert reason is None and q.options["ABCD".index(q.answer)] == "DNA"


def test_mcq_labelled_options_and_labelled_answer():
    q, reason = _check(_item(options=["A) ATP", "B) DNA", "C) RNA", "D) CO2"], answer="C) RNA"))
    assert reason is None and q.options["ABCD".index(q.answer)] == "RNA"


@pytest.mark.parametrize(
    ("changes", "slot", "reason"),
    [
        ({"options": ["ATP", "atp", "RNA", "CO2"]}, None, "mcq_duplicate_options"),
        ({"options": ["ATP", "DNA", "RNA"]}, None, "mcq_not_4_options"),
        ({"options": ["ATP", "DNA", "RNA", "CO2", "O2"]}, None, "mcq_not_4_options"),
        ({"answer": "Glucose"}, None, "mcq_answer_not_in_options"),
        ({"answer": True}, None, "mcq_answer_not_in_options"),
        ({"segment_id": 500}, None, "segment_out_of_range"),
        ({"type": "true_false"}, None, "wrong_type"),
        ({"question": "  "}, None, "empty_question"),
        ({"explanation": ""}, None, "empty_explanation"),
        ({}, "no-slot", "unknown_or_filled_slot"),
        ({"type": "true_false", "answer": "maybe", "options": []}, Slot(1, "true_false", "easy"),
         "true_false_answer_not_boolean"),
        ({"type": "short_answer", "answer": " ", "options": []}, Slot(1, "short_answer", "easy"),
         "short_answer_empty_answer"),
    ],
)
def test_invalid_items_are_rejected_with_a_reason(changes, slot, reason):
    s = None if slot == "no-slot" else (slot or Slot(1, "mcq", "easy"))
    q, got = _check(_item(**changes), slot=s)
    assert q is None and got == reason


def test_duplicate_question_is_rejected():
    seen = {"which molecule carries energy"}
    assert _check(_item(question="Which molecule carries ENERGY?"), seen=seen) == (None, "duplicate_question")


def test_true_false_and_short_answer_normalisation():
    tf, _ = _check(_item(type="true_false", answer="False", options=[]), slot=Slot(1, "true_false", "easy"))
    assert tf.answer is False and tf.options is None
    sa, _ = _check(_item(type="short_answer", answer="ATP stores energy", options=[], key_points=[]),
                   slot=Slot(1, "short_answer", "hard"))
    assert sa.answer == "ATP stores energy" and sa.key_points == ["ATP stores energy"]


# ---------------------------------------------------------------------------- generator


def _gen(quiz_generator, **kw):
    args = dict(lecture_id=uuid.uuid4(), user_id=None, title="Cells", topics=TOPICS, segments=SEGS,
                num_questions=6, types=["mcq", "true_false", "short_answer"], difficulty="medium")
    args.update(kw)
    return quiz_generator.generate(**args)


def _assert_all_valid(questions):
    for q in questions:
        if q.type == "mcq":
            assert len(q.options) == 4 and len({o.lower() for o in q.options}) == 4
            assert q.answer in "ABCD"
        elif q.type == "true_false":
            assert isinstance(q.answer, bool)
        else:
            assert q.answer and q.key_points
        assert q.source_start == SEGS[q.segment_id].start_sec
        assert q.topic == topic_of(TOPICS, q.segment_id)


def test_generator_returns_requested_mix_in_one_call(quiz_generator, fake_llm):
    draft = _gen(quiz_generator)
    assert len(draft.questions) == 6
    assert [q.type for q in draft.questions] == ["mcq", "true_false", "short_answer"] * 2
    assert {q.difficulty for q in draft.questions} == {"medium"}
    _assert_all_valid(draft.questions)
    assert fake_llm.tasks == ["quiz"]
    assert draft.meta["requested"] == 6 and draft.meta["generated"] == 6 and draft.meta["invalid_items"] == 0
    assert draft.meta["prompt_version"] == "quiz@v1" and draft.prompt_version == "quiz@v1"


def test_invalid_items_are_regenerated(quiz_generator, fake_llm):
    fake_llm.quiz_defects = ["duplicate_options", "answer_not_in_options", "segment_out_of_range", "drop"]
    draft = _gen(quiz_generator, num_questions=4, types=["mcq"])
    assert len(draft.questions) == 4
    _assert_all_valid(draft.questions)
    assert fake_llm.tasks == ["quiz", "quiz"]  # one extra request for the 4 bad slots
    assert "Already asked" in fake_llm.user_messages[1]
    assert draft.meta["invalid_items"] == 3 and draft.meta["regeneration_requests"] == 1
    assert draft.meta["invalid_reasons"] == {
        "mcq_duplicate_options": 1, "mcq_answer_not_in_options": 1, "segment_out_of_range": 1,
    }
    second = fake_llm.user_messages[1]
    assert second.count("- slot ") == 4  # only the failed slots were asked again


def test_generator_gives_up_after_max_rounds(quiz_generator, fake_llm, settings):
    fake_llm.quiz_always_invalid = True
    with pytest.raises(QuizGenerationError) as exc:
        _gen(quiz_generator, num_questions=2, types=["mcq"])
    assert fake_llm.tasks == ["quiz"] * (1 + settings.quiz_max_regen_rounds)
    assert exc.value.details["invalid_reasons"]["slot_unfilled"] == 2


def test_partial_quiz_when_some_slots_never_validate(quiz_generator, fake_llm, settings):
    settings.quiz_max_regen_rounds = 0
    fake_llm.quiz_defects = ["wrong_type"]
    draft = _gen(quiz_generator, num_questions=3, types=["mcq"])
    assert len(draft.questions) == 2 and draft.meta["generated"] == 2 and draft.meta["requested"] == 3
    assert draft.meta["invalid_reasons"] == {"wrong_type": 1, "slot_unfilled": 1}


def test_questions_spread_over_batches_and_logged(quiz_generator, fake_llm, settings, session_factory):
    settings.quiz_context_max_tokens = 80  # force several batches
    lid = uuid.uuid4()
    draft = _gen(quiz_generator, lecture_id=lid, num_questions=4, types=["true_false"])
    assert len(draft.questions) == 4 and draft.meta["batches"] > 1
    assert len(fake_llm.tasks) == 4  # one request per batch that got a question
    _assert_all_valid(draft.questions)
    assert {q.topic for q in draft.questions} == {"Glycolysis", "Krebs cycle"}
    with session_factory() as s:
        rows = list(s.scalars(select(LLMCall).where(LLMCall.task == "quiz")))
    assert len(rows) == 4 and all(r.prompt_version == "quiz@v1" and r.status == "ok" for r in rows)


def test_rate_limit_is_not_swallowed(quiz_generator, fake_llm, settings):
    settings.llm_max_retries = 0
    fake_llm.fail["quiz"] = rate_limited()
    from app.services.llm.errors import RateLimitedError

    with pytest.raises(RateLimitedError):
        _gen(quiz_generator)
