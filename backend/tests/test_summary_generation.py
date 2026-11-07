"""Summary/topics/notes generation: windows, grounding of timestamps, map-reduce, prompt content."""

import re
from types import SimpleNamespace

import pytest

from app.services.generation.summary import (
    LectureGenerator,
    Topic,
    TopicItem,
    TranscriptEmptyError,
    Window,
    build_windows,
    merge_adjacent,
    numbered_lines,
    resolve_topics,
)
from app.services.llm.prompts import PromptRegistry


def segs(n: int, *, sec: float = 10.0, words: int = 20, start_idx: int = 0):
    """n consecutive segments of `sec` seconds, each with `words` words."""
    return [
        SimpleNamespace(idx=start_idx + i, start_sec=(start_idx + i) * sec, end_sec=(start_idx + i + 1) * sec,
                        text=" ".join(f"w{i}" for _ in range(words)))
        for i in range(n)
    ]


# ---------------------------------------------------------------------------- windows


def test_short_transcript_is_one_window():
    ws = build_windows(segs(10), window_sec=600, window_max_tokens=2500, single_pass_max_tokens=3500)
    assert len(ws) == 1 and ws[0].first_idx == 0 and ws[0].last_idx == 9


def test_long_transcript_is_split_by_time_and_tokens():
    s = segs(200, sec=10, words=30)  # 2000 s
    ws = build_windows(s, window_sec=600, window_max_tokens=10_000, single_pass_max_tokens=100)
    assert len(ws) >= 3
    assert all(w.duration_sec <= 610 for w in ws)
    assert [w.first_idx for w in ws][0] == 0 and ws[-1].last_idx == 199
    for a, b in zip(ws, ws[1:]):
        assert b.first_idx == a.last_idx + 1  # contiguous, no segment lost

    tight = build_windows(s, window_sec=6000, window_max_tokens=500, single_pass_max_tokens=100)
    assert all(len(numbered_lines(w.segments)) / 4 <= 500 for w in tight)


def test_short_tail_is_folded_into_previous_window():
    s = segs(65, sec=10, words=5)  # 650 s: 600 s window + 50 s tail
    ws = build_windows(s, window_sec=600, window_max_tokens=10_000, single_pass_max_tokens=10)
    assert len(ws) == 1 and ws[0].last_idx == 64


# ---------------------------------------------------------------------------- grounding


def test_resolve_topics_clamps_orders_and_covers_window():
    w = Window(1, segs(10, start_idx=20))  # ids 20..29
    raw = [
        TopicItem(title="B", start_segment=26, end_segment=99, key_points=["b"]),  # beyond the window
        TopicItem(title="A", start_segment=5, end_segment=27, key_points=["a"]),  # before + overlapping
        TopicItem(title="C", start_segment=24, end_segment=22, key_points=[]),  # reversed, inside A
    ]
    out = resolve_topics(raw, w)
    assert [(t.title, t.start_segment, t.end_segment) for t in out] == [("A", 20, 27), ("B", 28, 29)]
    assert out[0].key_points == ["a"]  # C was fully inside A: dropped as a topic


def test_merge_adjacent_same_title_across_windows():
    t = [Topic("Intro", 0, 5, ["x"]), Topic("intro!", 6, 9, ["y"]), Topic("Next", 10, 12)]
    out = merge_adjacent(t)
    assert [(x.title, x.start_segment, x.end_segment, x.key_points) for x in out] == [
        ("Intro", 0, 9, ["x", "y"]), ("Next", 10, 12, []),
    ]


# ---------------------------------------------------------------------------- generator


def test_single_pass_generation(generator, fake_llm, llm_provider):
    s = segs(12)  # 0..120 s
    result = generator.generate(lecture_id=None, user_id=None, title="Neural nets", segments=s)

    assert fake_llm.tasks == ["topics", "notes", "notes", "summary"]
    topics = result.notes["topics"]
    assert [(t["title"], t["start"], t["end"]) for t in topics] == [("Topic 0", 0.0, 70.0), ("Topic 5", 70.0, 120.0)]
    assert all(t["notes_md"].startswith("- **Topic") for t in topics)
    # Definitions: timestamp looked up from the segment; an out-of-window id gets no timestamp.
    assert result.summary["definitions"] == [
        {"term": "Term 0", "definition": "as explained (not stated in lecture)", "timestamp": 0.0, "segment_id": 0},
        {"term": "Ghost", "definition": "id outside the window", "timestamp": None, "segment_id": None},
    ]
    assert result.summary["key_takeaways"] == ["Takeaway one", "Takeaway two"]
    meta = result.summary["meta"]
    assert meta["mode"] == "single_pass" and meta["windows"] == 1 and meta["llm_calls"] == 4
    assert meta["prompt_versions"] == {"topics": "topics@v1", "notes": "notes@v1", "summary": "summary@v1"}
    assert meta["prompt_version"] == "summary@v1" and meta["input_tokens"] == 4 * 300
    # Summary source is the transcript itself in single-pass mode; the model never sees times.
    assert "w0 w0" in fake_llm.user_messages[-1] and "full lecture transcript" in fake_llm.user_messages[-1]
    topics_input = fake_llm.user_messages[0].split("Transcript:")[1]
    assert topics_input.strip().startswith("[0] w0")
    assert not re.search(r"\d+:\d\d", "".join(fake_llm.user_messages))  # no clock times anywhere
    # Groq gets reasoning_effort=low (fewer hidden tokens against the free-tier TPM limit).
    assert {c["reasoning_effort"] for c in llm_provider.calls} == {"low"}
    assert all(c["json_mode"] for c in llm_provider.calls)


def test_map_reduce_generation(settings, lecture_llm_client, fake_llm):
    settings.summary_single_pass_max_tokens = 50
    settings.summary_window_sec = 60
    gen = LectureGenerator(settings, lecture_llm_client)
    s = segs(18)  # 180 s -> 3 windows of 60 s

    result = gen.generate(lecture_id=None, user_id=None, title="Long", segments=s)

    assert fake_llm.tasks.count("topics") == 3
    meta = result.summary["meta"]
    assert meta["mode"] == "map_reduce" and meta["windows"] == 3
    topics = result.notes["topics"]
    assert topics[0]["start"] == 0.0 and topics[-1]["end"] == 180.0
    for a, b in zip(topics, topics[1:]):
        assert a["end"] == b["start"]  # contiguous across window boundaries
    # REDUCE uses the topic key points, not the raw transcript.
    reduce_input = fake_llm.user_messages[-1]
    assert "## Topic 0" in reduce_input and "- point 0" in reduce_input and "w0 w0" not in reduce_input
    assert fake_llm.tasks.count("notes") == len(topics)


def test_empty_transcript_is_rejected(generator):
    with pytest.raises(TranscriptEmptyError):
        generator.generate(lecture_id=None, user_id=None, title="Silence",
                           segments=[SimpleNamespace(idx=0, start_sec=0, end_sec=1, text="  ")])


def test_invalid_json_twice_raises_clear_error(generator, fake_llm):
    fake_llm.invalid["topics"] = True
    with pytest.raises(Exception) as exc:
        generator.generate(lecture_id=None, user_id=None, title="X", segments=segs(3))
    assert getattr(exc.value, "code", None) == "LLM_OUTPUT_INVALID"
    assert fake_llm.tasks == ["topics", "topics"]  # one repair attempt, then stop


@pytest.mark.parametrize("prompt_id", ["topics", "notes", "summary"])
def test_prompts_are_grounded_and_versioned(prompt_id):
    p = PromptRegistry().get(prompt_id)
    assert p.version == "v1"
    text = p.system.lower()
    assert "only" in text and "outside knowledge" in text
    assert "(not stated in lecture)" in p.system
    assert "never write clock times" in text or "do not write timestamps" in text
