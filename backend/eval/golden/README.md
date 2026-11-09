# Golden sets (Phase 11 evaluation)

Hand-written questions about ONE lecture, used by `python -m eval.run`. **Written by the team, never by an LLM.**
The labels here are the ground truth for metrics M6 (retrieval), M7 (faithfulness / correctness) and M8 (refusals).

## Where

`backend/eval/golden/<name>.jsonl`, e.g. `golden_v1.jsonl`. `<name>` is what you pass as `--set`.
The lecture is chosen on the command line (`--lecture-id <uuid>`), so one file belongs to one lecture.

## Format: one JSON object per line

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Unique within the file, e.g. `q01` |
| `question` | string | The question as a student would ask it |
| `answerable` | bool | `true` if the lecture answers it |
| `gold_start` | number or null | Seconds from the start of the lecture where the answer begins (required when `answerable` is true) |
| `gold_end` | number or null | Seconds where the answer ends (≥ `gold_start`) |
| `reference_answer` | string or null | Your short correct answer (required when `answerable` is true) |
| `kind` | string | `on_topic` (the lecture covers it), `near_topic` (same field, not covered), `off_topic` (unrelated) |
| `difficulty` | string, optional | Your label, e.g. `Easy` / `Medium` / `Hard` (stored for reporting; not used in the metrics) |

For an unanswerable question, `reference_answer` may hold the expected refusal text; it is kept for the record,
and the correctness judge only grades answerable questions.

## Sets in this folder

| File | Lecture | Questions | Source |
|---|---|---|---|
| `cloud_native_l1.jsonl` | "API-driven Cloud Native Solutions" | 20 (12 answerable, 4 near-topic, 4 off-topic) | Converted verbatim from the team's spreadsheet `AI_Study_Buddy_Lecture_Evaluation_20Q.xlsx` (sheet "Questions") on 2026-11-09. Only two timestamps were corrected, on the team's instruction: Q10 `gold_start` 1819 → 1810, Q11 `gold_end` 2397 → 2467. Not used for now: the full recording is not in the app |
| `ci_lecture.jsonl` | "Scalable_recording_CI" (Continuous Integration) | 20 (12 answerable, 4 near-topic, 4 off-topic) | Converted verbatim from the team's final spreadsheet `CI_Lecture_Golden_Set_final.xlsx` (sheet "Golden set") on 2026-11-09; `question_id` n → `qNN` (ids q01, q03–q21; there is no q02), `answerable` taken from the sheet (it matches `kind`). Questions and answers unchanged. Seven gold ranges were re-aligned to the app's transcript of the 648.8 s recording, approved by the team on 2026-11-09 (they were 5–42 s off): q06 76–119 → 70.4–105.9, q08 122–131 → 105.9–124.9, q09 139–168 → 124.9–157.3, q10 168–204 → 143.1–191.5, q11 575–613 → 532.5–566.9, q12 622–650 → 623.4–648.8, q16 613–682 → 571.9–623.4 |

Before running a set on a newly uploaded recording, check that the transcript times line up with the labels
(e.g. `python -m eval.segments --lecture-id <id> --segments` and find a phrase you labelled).

Example of the SHAPE only (placeholder values, not a real question):

```json
{"id": "q01", "question": "<your question>", "answerable": true, "gold_start": 0.0, "gold_end": 0.0, "reference_answer": "<your answer>", "kind": "on_topic"}
{"id": "q02", "question": "<your question>", "answerable": false, "gold_start": null, "gold_end": null, "reference_answer": null, "kind": "off_topic"}
```

Suggested size (IMPLEMENTATION_PLAN §7.3): about 30 questions per lecture, about 20 answerable and 10 not
(mix `near_topic` and `off_topic`; near-topic questions are the hard ones for the threshold).

## Helpers

```
cd backend
python -m eval.segments --lecture-id <uuid>          # the lecture's retrieval chunks with their start/end times
python -m eval.validate --set golden_v1              # checks the file (fields, types, times inside the lecture)
python -m eval.run --set golden_v1 --lecture-id <uuid> --generator all
```

`gold_start`/`gold_end` should cover the part of the lecture that answers the question. Retrieval counts a chunk as
relevant when its time range overlaps `[gold_start, gold_end]`.
