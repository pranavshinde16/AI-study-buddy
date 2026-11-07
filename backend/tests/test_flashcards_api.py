"""Flashcard deck generation (definitions + concepts, no duplicates, cached), listing with the due
filter, and Leitner reviews. Fake LLM, no network."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.learning import Flashcard
from app.services.flashcards import BOX_INTERVAL_DAYS, _aware
from app.services.generation.flashcards import card_key


@pytest.mark.parametrize(
    ("front", "key"),
    [
        ("What is a Neuron?", "neuron"),
        ("neuron", "neuron"),
        ("Define the neuron.", "neuron"),
        ("What does ATP stand for?", "atp"),
        ("How does part 0 work?", "part 0 work"),
        ("how does PART 0 work", "part 0 work"),
        ("Why does segment 9 matter?", "segment 9 matter"),
    ],
)
def test_card_key(front, key):
    assert card_key(front) == key


def _deck(client, headers, lid, **body):
    return client.post(f"/api/lectures/{lid}/flashcards", headers=headers, json=body)


def test_deck_has_definitions_and_concepts_without_duplicates(client, auth_headers, make_ready_lecture, fake_llm):
    lid = make_ready_lecture()
    r = _deck(client, auth_headers, lid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is False
    cards = body["cards"]
    kinds = [c["kind"] for c in cards]
    assert kinds.count("definition") == 2  # both definitions from the (single-pass) summary
    defs = {c["front"]: c for c in cards if c["kind"] == "definition"}
    assert set(defs) == {"Term 0", "Ghost"}
    assert defs["Term 0"]["timestamp"] == 0.0 and defs["Term 0"]["topic"] == "Topic 0"
    assert defs["Ghost"]["timestamp"] is None and defs["Ghost"]["topic"] is None  # no valid segment: no guess

    concepts = [c for c in cards if c["kind"] == "concept"]
    assert concepts, "the fake LLM's valid concept cards are kept"
    keys = [card_key(c["front"]) for c in cards]
    assert len(keys) == len(set(keys)), "no duplicate cards"
    assert not any(c["front"].startswith("What is Term") for c in concepts), "definition duplicates dropped"
    assert not any(c["front"] == "Where is this from?" for c in concepts), "out-of-range segment dropped"
    assert all(c["timestamp"] is not None and c["timestamp"] % 10 == 0 for c in concepts)
    assert all(c["box"] == 1 and c["due"] is True for c in cards)
    assert body["total"] == len(cards) == body["due"]

    meta = body["meta"]
    assert meta["definition_cards"] == 2 and meta["concept_cards"] == len(concepts)
    assert meta["dropped"]["duplicate"] >= 2 and meta["dropped"]["segment_out_of_range"] >= 1
    assert meta["prompt_version"] == "flashcards@v1"

    # cached: same deck, no LLM call
    n = len(fake_llm.tasks)
    again = _deck(client, auth_headers, lid).json()
    assert again["cached"] is True and again["meta"] is None
    assert [c["id"] for c in again["cards"]] == [c["id"] for c in cards]
    assert len(fake_llm.tasks) == n


def test_regenerate_replaces_the_deck(client, auth_headers, make_ready_lecture, db):
    lid = make_ready_lecture()
    first = {c["id"] for c in _deck(client, auth_headers, lid).json()["cards"]}
    new = _deck(client, auth_headers, lid, regenerate=True).json()
    assert new["cached"] is False
    assert first.isdisjoint({c["id"] for c in new["cards"]})
    assert db.scalar(select(Flashcard.id).where(Flashcard.id == uuid.UUID(next(iter(first))))) is None


def test_deck_respects_max_cards(client, auth_headers, make_ready_lecture, settings):
    settings.flashcards_max_cards = 3
    lid = make_ready_lecture()
    body = _deck(client, auth_headers, lid).json()
    assert body["total"] <= 3


def test_deck_needs_notes(client, auth_headers, make_ready_lecture):
    lid = make_ready_lecture(summarize=False)
    r = _deck(client, auth_headers, lid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOTES_NOT_GENERATED"


def test_leitner_review_moves_cards_between_boxes(client, auth_headers, make_ready_lecture, db):
    lid = make_ready_lecture()
    card = _deck(client, auth_headers, lid).json()["cards"][0]
    url = f"/api/flashcards/{card['id']}/review"

    for box in (2, 3, 4, 5, 5):  # knew it: up one box each time, never above 5
        before = datetime.now(UTC)
        r = client.post(url, headers=auth_headers, json={"knew": True})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["box"] == box and out["due"] is False and out["last_reviewed_at"]
        due = _aware(datetime.fromisoformat(out["due_at"]))
        assert due - before >= timedelta(days=BOX_INTERVAL_DAYS[box]) - timedelta(seconds=5)

    out = client.post(url, headers=auth_headers, json={"knew": False}).json()
    assert out["box"] == 1 and out["due"] is True  # didn't know: back to box 1, due again now

    db.expire_all()
    stored = db.get(Flashcard, uuid.UUID(card["id"]))
    assert stored.box == 1


def test_due_filter(client, auth_headers, make_ready_lecture):
    lid = make_ready_lecture()
    cards = _deck(client, auth_headers, lid).json()["cards"]
    client.post(f"/api/flashcards/{cards[0]['id']}/review", headers=auth_headers, json={"knew": True})
    due = client.get(f"/api/lectures/{lid}/flashcards?due=true", headers=auth_headers).json()
    assert due["total"] == len(cards) - 1 and cards[0]["id"] not in {c["id"] for c in due["cards"]}
    everything = client.get(f"/api/lectures/{lid}/flashcards", headers=auth_headers).json()
    assert everything["total"] == len(cards) and everything["due"] == len(cards) - 1


def test_review_validation_and_ownership(client, auth_headers, make_ready_lecture, make_user):
    lid = make_ready_lecture()
    card = _deck(client, auth_headers, lid).json()["cards"][0]
    url = f"/api/flashcards/{card['id']}/review"
    assert client.post(url, headers=auth_headers, json={}).status_code == 422
    make_user("eve@example.com", "another-password-123", "Eve")
    tok = client.post("/api/auth/login", json={"email": "eve@example.com", "password": "another-password-123"})
    eve = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    r = client.post(url, headers=eve, json={"knew": True})
    assert r.status_code == 404 and r.json()["error"]["code"] == "FLASHCARD_NOT_FOUND"
    assert client.get(f"/api/lectures/{lid}/flashcards", headers=eve).status_code == 404
    assert _deck(client, eve, lid).status_code == 404
    assert client.post(f"/api/flashcards/{uuid.uuid4()}/review", headers=auth_headers,
                       json={"knew": True}).status_code == 404
