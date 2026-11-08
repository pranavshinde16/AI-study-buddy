import json
import random

import pytest

import metrics as M
import prepare_data as P
from eval_runner import OllamaBackend, prompt_messages
from prompts import REFUSAL_ANSWER, RESPONSE_MARKER


def rows(n=40):
    out = []
    for i in range(n):
        out.append({
            "question": f"What does organelle {i} make?",
            "correct_answer": f"substance{i}",
            "distractor1": f"wrong{i}a", "distractor2": f"wrong{i}b", "distractor3": f"wrong{i}c",
            "support": f"Cells are small. Organelle {i} makes substance{i} for the cell. It is round.",
        })
    out.append({**out[0], "support": "  "})  # dropped: empty support
    return out


def chars(messages):  # fake token counter: 1 token per 4 characters
    return sum(len(m["content"]) for m in messages) // 4


def test_clean_rows_drops_empty_support():
    items, dropped = P.clean_rows(rows())
    assert dropped == 1 and len(items) == 40


def test_supporting_sentence_is_taken_from_the_data():
    assert P.supporting_sentence("A b. The mitochondria makes ATP. End.", "ATP") == "The mitochondria makes ATP."
    assert P.supporting_sentence("Nothing here.", "ATP") is None
    item = P.clean_rows(rows())[0][3]
    assert P.reference_answer(item) == ("Substance3. Organelle 3 makes substance3 for the cell.", True)


def test_gqa_example_cites_the_gold_excerpt_and_hides_the_answer_elsewhere():
    items, _ = P.clean_rows(rows())
    ex = P.build_gqa(items[5], items, random.Random(1))
    target = json.loads(ex["messages"][-1]["content"])
    gold = ex["meta"]["gold_citation"]
    assert list(target) == ["answerable", "answer", "citations"]
    assert target["answerable"] is True and target["citations"] == [gold] and f"[{gold}]" in target["answer"]
    user = ex["messages"][1]["content"]
    blocks = user.split("Transcript excerpts:\n", 1)[1].strip().split("\n\n")
    assert len(blocks) == ex["meta"]["n_excerpts"] in (2, 3)
    for b in blocks:
        has = "substance5" in b
        assert has == b.startswith(f"[{gold}]")  # only the gold excerpt contains the answer


def test_refusal_and_mcq_examples():
    items, _ = P.clean_rows(rows())
    ref = P.build_refusal(items[7], items, random.Random(2))
    t = json.loads(ref["messages"][-1]["content"])
    assert t == {"answerable": False, "answer": REFUSAL_ANSWER, "citations": []}
    assert "substance7" not in ref["messages"][1]["content"]
    mcq = P.build_mcq(items[9], random.Random(3))
    t = json.loads(mcq["messages"][-1]["content"])
    assert sorted(t["options"]) == sorted(["substance9", "wrong9a", "wrong9b", "wrong9c"])
    assert t["options"]["ABCD".index(t["answer"])] == "substance9"


def test_build_split_is_deterministic_and_fits_the_token_limit():
    items, _ = P.clean_rows(rows())
    a, stats = P.build_split(items, (20, 15, 3, 2), "train", chars, max_len=800)
    b, _ = P.build_split(items, (20, 15, 3, 2), "train", chars, max_len=800)
    assert a == b
    assert stats["by_task"] == {"gqa": 15, "refusal": 3, "mcq": 2}
    assert all(chars(e["messages"]) <= 800 for e in a)
    assert all("_src" not in e for e in a)
    assert len({e["meta"]["sciq_index"] for e in a}) == 20  # each SciQ item used once


def test_long_examples_lose_distractors_before_being_dropped():
    items, _ = P.clean_rows(rows())
    ex = P.build_gqa(items[1], items, random.Random(5))
    full = chars(ex["messages"])
    fitted, n = P.fit_length(ex, chars, full - 1)
    assert fitted is not None and fitted["meta"]["reduced"] >= 1 and n <= full - 1
    gold = fitted["meta"]["gold_citation"]
    target = json.loads(fitted["messages"][-1]["content"])
    assert target["citations"] == [gold] and f"[{gold}]" in target["answer"]
    assert f"[{gold}] Cells are small. Organelle 1" in fitted["messages"][1]["content"]
    assert P.fit_length(ex, chars, 10)[0] is None


def test_split_plan_matches_the_brief():
    assert P.PLAN["train"] == (3000, 2250, 450, 300)
    assert P.PLAN["validation"] == (300, 225, 45, 30)
    assert P.PLAN["test"] == (500, 375, 75, 50)
    assert RESPONSE_MARKER.endswith("</think>\n\n")


# ---------------------------------------------------------------- metrics

def test_text_metrics():
    assert M.normalize("The A-team, an ace!") == "team ace"
    assert M.contains_answer("It is ATP [C1].", "atp") and not M.contains_answer("ATPase", "ATP")
    assert M.token_f1("the cat sat", "cat sat down") == pytest.approx(0.8)
    assert M.rouge_l("w x y z", "w y z") == pytest.approx(2 * (3 / 4) * 1 / (3 / 4 + 1))
    assert M.strip_citations("ATP [C1]. Yes [ c2 ]") == "ATP . Yes"


def test_parsers_tolerate_think_and_fences():
    assert M.parse_rag('<think>hm</think>```json\n{"answerable": true, "answer": "x"}\n```') == {
        "answerable": True, "answer": "x", "citations": []}
    assert M.parse_rag('{"answerable": "yes", "answer": "x"}') is None
    assert M.parse_mcq('{"question": "q", "options": ["a","b","c","d"], "answer": "b)"}')["answer"] == "B"
    assert M.parse_mcq('{"question": "q", "options": ["a","a","c","d"], "answer": "A"}') is None


def _item(task, i, **meta):
    return {"id": f"{task}{i}", "task": task, "meta": meta}


def test_score_items_counts_accuracy_refusals_and_json():
    items = [
        _item("gqa", 1, correct_answer="ATP", reference_answer="ATP. Cells make ATP.", gold_citation="C2"),
        _item("gqa", 2, correct_answer="DNA", reference_answer="DNA. It stores genes.", gold_citation="C1"),
        _item("refusal", 3, correct_answer="x"),
        _item("refusal", 4, correct_answer="y"),
        _item("mcq", 5, correct_answer="mitosis"),
    ]
    outputs = [
        {"text": '{"answerable": true, "answer": "ATP. Cells make ATP [C2].", "citations": ["C2"]}', "latency_ms": 10},
        {"text": '{"answerable": false, "answer": "Not covered.", "citations": []}', "latency_ms": 20},
        {"text": '{"answerable": false, "answer": "No.", "citations": []}', "latency_ms": 30},
        {"text": "garbage", "latency_ms": 40},
        {"text": '{"question": "q", "options": ["meiosis","mitosis","x","y"], "answer": "B"}', "latency_ms": 50},
    ]
    s = M.score_items(items, outputs)["summary"]
    assert s["gqa"]["accuracy"] == 0.5 and s["gqa"]["gold_citation_rate"] == 0.5
    assert s["gqa"]["token_f1"] == 0.5  # 1.0 for the exact answer, 0 for the refusal's text vs reference
    assert s["refusal"]["confusion"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    assert s["refusal"]["precision"] == 0.5 and s["refusal"]["recall"] == 0.5
    assert s["rag_json_valid_rate"] == 0.75
    assert s["mcq"] == {"n": 1, "json_valid_rate": 1.0, "answer_matches_source_rate": 1.0}
    assert s["latency_ms"]["mean"] == 30.0 and s["latency_ms"]["p50"] == 30.0


# ---------------------------------------------------------------- Ollama backend (fake HTTP)

class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_backend_sends_the_app_request_shape():
    sent = []

    def opener(req, timeout):
        sent.append(json.loads(req.data))
        return _Resp({"choices": [{"message": {"content": '{"answerable": false, "answer": "no"}'}}]})

    item = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                         {"role": "assistant", "content": "gold"}]}
    out = OllamaBackend(opener=opener).generate("study-buddy-qwen", [item])
    assert out[0]["text"].startswith('{"answerable"') and out[0]["latency_ms"] is not None
    assert sent[0]["messages"] == prompt_messages(item) == item["messages"][:2]
    assert sent[0]["response_format"] == {"type": "json_object"} and sent[0]["temperature"] == 0


def test_ollama_backend_records_connection_errors():
    import urllib.error

    def opener(req, timeout):
        raise urllib.error.URLError("refused")

    out = OllamaBackend(opener=opener).generate("m", [{"messages": [{"role": "user", "content": "u"}]}])
    assert out[0]["text"] == "" and out[0]["latency_ms"] is None and "URLError" in out[0]["error"]
