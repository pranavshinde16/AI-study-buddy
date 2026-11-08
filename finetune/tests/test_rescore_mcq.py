"""Secondary MCQ checks (rescore_mcq.py), offline."""

import json

import metrics as M
from rescore_mcq import rescore


def test_strip_option_label_and_loose_match():
    assert M.strip_option_label("B. It releases energy.") == "It releases energy."
    assert M.strip_option_label("(c) heat") == "heat"
    assert M.strip_option_label("Atoms") == "Atoms"  # a capital letter without a label stays
    assert M.mcq_loose_match("exothermic", "exothermic reactions")
    assert M.mcq_loose_match("A. exothermic reactions", "exothermic")
    assert not M.mcq_loose_match("endothermic", "exothermic reactions")


def _item(i, passage, correct):
    return {"id": f"m{i}", "task": "mcq", "meta": {"correct_answer": correct},
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": f"Passage:\n{passage}"}]}


def _pred(i, obj, strict):
    return {"id": f"m{i}", "task": "mcq", "output": obj if isinstance(obj, str) else json.dumps(obj),
            "answer_matches_source": strict}


def test_rescore_counts_invalid_as_miss_and_reports_valid_only():
    items = [_item(1, "Exothermic reactions release heat.", "exothermic reactions"),
             _item(2, "Fungi are saprophytes.", "parasitic"),
             _item(3, "Whatever.", "x")]
    preds = [
        _pred(1, {"question": "q", "options": ["endothermic", "exothermic", "ionic", "neutral"], "answer": "B"}, False),
        _pred(2, {"question": "q", "options": ["saprophytes", "parasites", "hosts", "algae"], "answer": "A"}, False),
        _pred(3, '{"question": "q", "options": ["a", "a", "a", "a"], "answer": "A"}', False),  # duplicates: invalid
        {"id": "g1", "task": "gqa", "output": "{}"},
    ]
    r = rescore(items, preds)
    assert r["n_mcq"] == 3 and r["n_json_valid"] == 2
    assert r["strict_answer_matches_source_rate"] == 0.0
    assert r["loose_match_rate"] == round(1 / 3, 4)          # only item 1
    assert r["answer_in_passage_rate"] == round(2 / 3, 4)    # "exothermic", "saprophytes"
    assert r["valid_only"] == {"strict_match": 0.0, "loose_match": 0.5, "answer_in_passage": 1.0}
    assert r["invalid_reasons"] == {"duplicate_options": 1}


def test_output_length_stats():
    from output_stats import length_stats
    preds = [{"task": "gqa", "output": "abcd"}, {"task": "gqa", "output": "ab"}, {"task": "mcq", "output": "abcdef"}]
    s = length_stats(preds, count_tokens=lambda t: len(t) // 2)
    assert s["all"] == {"n": 3, "mean_chars": 4.0, "mean_tokens": 2.0}
    assert s["gqa"] == {"n": 2, "mean_chars": 3.0, "mean_tokens": 1.5}
    assert length_stats(preds)["mcq"] == {"n": 1, "mean_chars": 6.0}
    b = length_stats(preds, count_tokens=len, batch_size=2)["all"]  # batches [4, 2] and [6] -> maxes 4, 6
    assert b["batch_size"] == 2 and b["mean_batch_max_tokens"] == 5.0


def test_stratified_subset_keeps_task_mix_and_is_seeded():
    from evaluate import stratified_subset
    items = ([{"id": f"g{i}", "task": "gqa"} for i in range(375)] + [{"id": f"r{i}", "task": "refusal"} for i in range(75)]
             + [{"id": f"m{i}", "task": "mcq"} for i in range(50)])
    sub = stratified_subset(items, 50)
    tasks = [it["task"] for it in sub]
    assert len(sub) == 50 and tasks.count("gqa") == 38 and tasks.count("refusal") == 7 and tasks.count("mcq") == 5
    assert [it["id"] for it in sub] == [it["id"] for it in stratified_subset(items, 50)]  # same seed, same sample
    order = [items.index(it) for it in sub]
    assert order == sorted(order)  # file order kept
    assert stratified_subset(items, 1000) == items


def test_ollama_subset_run_writes_labelled_file(tmp_path, monkeypatch):
    import io
    import evaluate as E
    items = [{"id": f"x{i}", "task": "gqa" if i % 5 else "refusal", "meta": {"correct_answer": "ok", "reference_answer": "ok", "gold_citation": "C1"},
              "messages": [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": "{}"}]} for i in range(20)]
    src = tmp_path / "items.jsonl"
    src.write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    calls = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(req, timeout):
        calls.append(json.loads(req.data)["model"])
        body = {"choices": [{"message": {"content": '{"answerable": true, "answer": "ok [C1]", "citations": ["C1"]}'}}]}
        return Resp(json.dumps(body).encode())

    real = E.OllamaBackend
    monkeypatch.setattr(E, "OllamaBackend", lambda url: real(url, opener=fake_open))
    assert E.main(["--items", str(src), "--out", str(tmp_path), "--subset", "10"]) == 0
    rep = json.loads((tmp_path / "eval_ollama_subset10.json").read_text(encoding="utf-8"))
    assert rep["n_items"] == 10 and rep["subset"]["n"] == 10 and rep["subset"]["of_items"] == 20
    assert rep["warmup_request_per_model"] is True
    assert len(calls) == 2 * (10 + 1)  # one untimed warm-up per model
    assert rep["models"]["finetuned"]["latency_ms"]["n"] == 10
