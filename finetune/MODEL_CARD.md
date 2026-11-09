---
license: cc-by-nc-3.0
base_model: unsloth/Qwen3-1.7B
datasets:
  - allenai/sciq
language:
  - en
tags:
  - qwen3
  - lora
  - qlora
  - unsloth
  - gguf
  - grounded-qa
---

# study-buddy-qwen: Qwen3-1.7B fine-tuned on SciQ for grounded answers

> Every number below is copied from a file in `results/` (named in the **Source** column or next to the value).
> Values that no run has produced yet stay `TBD (run X)`.

## Summary

A LoRA fine-tune of **Qwen3-1.7B** that answers a question **only from numbered excerpts** (`[C1]`, `[C2]`, …).
It replies in JSON (`answerable`, `answer`, `citations`) and refuses when the excerpts don't contain the answer.
It's the "finetuned" answer generator of the AI Study Buddy university project, served locally through Ollama.

| | |
|---|---|
| Base model | `unsloth/Qwen3-1.7B` @ `6262b50d6c1f8ee5e4ac750d710c33603bfc2a0c` |
| Method | 4-bit QLoRA (Unsloth), r = 16, alpha = 16, dropout 0, attention + MLP projections |
| Thinking mode | Off (`enable_thinking=False`) in training and evaluation; embedded in the GGUF's chat template for Ollama |
| Formats | LoRA adapter · merged 16-bit · GGUF q4_k_m |
| GGUF size | 1,107,404,864 bytes (training.json → `exports.gguf_bytes`) |
| Hugging Face Hub | [huggingface.co/TusharDecoded/study-buddy-qwen3-1.7b-sciq-lora](https://huggingface.co/TusharDecoded/study-buddy-qwen3-1.7b-sciq-lora) (**private**: LoRA adapter, GGUF q4_k_m and this card) |

## Training data

`allenai/sciq` @ `2c94ad3e1aafab77146f384e23536f97a4849815` (CC-BY-NC-3.0), official splits, seed 3407.
Rows without a support paragraph are removed. Source: `results/data_stats.json`.

| Split | Rows | Without support (dropped) | Examples used | Grounded QA / refusal / MCQ | Tokens mean / p95 / max |
|---|---|---|---|---|---|
| train | 11,679 | 1,198 | 3,000 | 2,250 / 450 / 300 | 626.0 / 926 / 1,024 |
| validation | 1,000 | 113 | 300 | 225 / 45 / 30 | 629.6 / 915 / 1,011 |
| test (evaluation only) | 1,000 | 116 | 500 | 375 / 75 / 50 | 634.5 / 924 / 1,018 |

- **Grounded QA:** the question + excerpts (its own support paragraph + 1–2 unrelated ones, shuffled) → the correct answer + the support sentence containing it + a citation.
- **Refusal:** the question + only unrelated paragraphs → `answerable: false`.
- **MCQ generation:** passage → question with the correct answer and SciQ's three distractors as JSON.

Maximum length is 1,024 tokens. Examples over it lose unrelated excerpts first (train: 99 grounded-QA and
10 refusal examples reduced, 6 dropped; data_stats.json → `events`).

## Training

Source: `results/training.json` unless stated otherwise.

| | |
|---|---|
| Hardware | Tesla T4 (`gpu`) |
| Epochs / steps | 1 / 188 (`global_steps`) |
| Learning rate / schedule | 2e-4, cosine, 10 warm-up steps |
| Effective batch size | 16 (4 × 4 gradient accumulation) |
| Precision | fp16 (no bf16 on T4) |
| Seed | 3407 |
| Validation loss | 0.1927 at step 25 → 0.1405 at step 188 (`log_history`, `final_eval.eval_loss`) |
| Training time | **≈ 30.2 min, reconstructed** (at least 28.9 min). See below |
| Library versions | unsloth 2026.10.8, transformers 5.17.0, trl 1.15.0, peft 0.21.2, bitsandbytes 0.50.2, torch 2.14.1+cu130, Python 3.13.16 (`versions`) |

**Why the training time is reconstructed.** The notebook's own measurement of the training session was lost.
After training had finished, step 6 was run again in a new Colab session. The Trainer resumed from the final
checkpoint (`checkpoint-188`), trained 0 steps, and overwrote `training.json` with that session's numbers
(`train_runtime` 0.0073 s). The weights were not affected: the final validation loss is the same as the original run's.

The figure in the table comes from `results/training_time_reconstructed.json`:
- the original run's progress bar, `[180/188 28:10 < 01:15, 0.11 it/s]`. Source: the screenshot
  [`docs/screenshots/training_progress.png`](../docs/screenshots/training_progress.png) in the project repository,
  which also shows the loss table,
- plus the logged evaluation at step 188 (46.7 s).

`checkpoint-188/trainer_state.json` can't help, because it stores no wall-clock times. The notebook now logs
every training session to `results/training_sessions.jsonl`, so a re-run can't erase the time again.

## Evaluation: base vs fine-tuned

Same 500 SciQ **test** items (fingerprint `f1234876f5b6c094`), same prompts, greedy decoding, max 256 new tokens, thinking off.
**Base** is the same 4-bit model with the LoRA adapter switched off; **fine-tuned** has it switched on (Colab T4).
Source: `results/eval_hf.json` → `models.<base|finetuned>.…`. No generation failed (`request_errors` 0 for both).

| Metric | Base | Fine-tuned | Key |
|---|---|---|---|
| Answer accuracy (grounded QA, n = 375) | 0.7227 | **0.9093** | `gqa.accuracy` |
| Token F1 | 0.3535 | **0.8339** | `gqa.token_f1` |
| ROUGE-L | 0.3378 | **0.8299** | `gqa.rouge_l` |
| Cites the right excerpt | 0.8613 | **0.984** | `gqa.gold_citation_rate` |
| Refusal precision | 0.4737 | **0.9221** | `refusal.precision` |
| Refusal recall (n = 75 should refuse) | 0.84 | **0.9467** | `refusal.recall` |
| Refusal confusion (tp / fp / fn / tn) | 63 / 70 / 12 / 305 | 71 / 6 / 4 / 369 | `refusal.confusion` |
| RAG JSON validity | 1.0 | 1.0 | `rag_json_valid_rate` |
| MCQ JSON validity (n = 50) | **0.9** | 0.82 ⚠ regression | `mcq.json_valid_rate` |
| MCQ answer matches source (**primary**, strict) | 0.08 | **0.22** | `mcq.answer_matches_source_rate` |
| Latency per answer, GPU, mean / p50 / p95 ms | **624.7 / 605.2 / 893.1** | 816.0 / 766.3 / 1,119.5 ⚠ regression | `latency_ms` |
| Latency per answer, Ollama CPU, **50-item subset** (mean / p95 ms) | 9,765.4 / 14,385.8 | 9,877.2 / 15,115.7 | eval_ollama_subset50.json → `latency_ms` |

### Gains

- **Answers in the trained format.** Token F1 and ROUGE-L more than double. The answers follow the target shape
  (answer + support sentence + citation) instead of free-form summaries.
- **Accuracy and citations.** QA accuracy rises from 0.7227 to 0.9093, and the right excerpt is cited in 0.984 of answers.
- **Refusals.** Refusal precision roughly doubles (0.4737 → 0.9221). The base model wrongly refused 70 answerable
  questions; the fine-tuned model refuses 6. Recall also rises (0.84 → 0.9467).

### Regressions

**MCQ JSON validity: 0.9 → 0.82.**
- All 9 invalid fine-tuned outputs are well-formed JSON with **four identical options**, which the validator rejects
  (`results/mcq_secondary_hf.json` → `invalid_reasons`: `duplicate_options` 9).
- The base model's 5 invalid outputs are broken JSON (4 not parseable, 1 with a wrong `options` field).
- **Likely cause:** MCQ generation is only 10 % of the training mix (300 examples). The model learned SciQ's short
  option style, but sometimes repeats the correct answer instead of producing distractors.
- The app's quiz feature doesn't use this model: it generates with the cloud model and validates and regenerates bad questions.

**GPU latency: mean 624.7 → 816.0 ms (p95 893.1 → 1,119.5 ms).**
- **Likely cause:** how the comparison is run. The fine-tuned pass computes the unmerged LoRA adapter on top of the
  4-bit weights at every generated token; the base pass switches the adapter off.
- **Output length doesn't explain it.** Answers got longer (mean 36.2 → 41.6 tokens), but latency is measured per
  batch of 8. The mean longest output per batch is about the same (64.5 base, 62.1 fine-tuned)
  (`results/output_stats_hf.json`).
- The served GGUF has the adapter merged in, so it has no adapter overhead. Through Ollama on CPU
  (50-item subset, `results/eval_ollama_subset50.json`), the mean latency is 9,765.4 ms (base) vs 9,877.2 ms
  (fine-tuned), about 1 % apart. This supports the adapter explanation.
- **Caveats:** this is only 50 items. The two GGUFs were also quantised separately: base from Ollama's `qwen3:1.7b`,
  fine-tuned from the merged model.

**Ollama subset, other metrics.** `eval_ollama_subset50.json` also has quality scores for the 50 items
(stratified 38 QA / 7 refusal / 5 MCQ, seed 3407, the sampled ids are recorded). They run through the app's serving
path (JSON mode, q4_k_m GGUF). With so few refusal and MCQ items, those rates are much less certain than the
500-item GPU results above, which remain the primary comparison.

### MCQ: secondary checks (added after the first results)

The strict primary metric counts a match only if the option the model marks as correct equals SciQ's answer.
That undercounts, because the model may ask about a different fact in the passage, or word the same answer
differently ("exothermic" vs "exothermic reactions").

Two looser checks were added **after the first results were seen**. They are re-scored from the saved predictions
by `rescore_mcq.py`, with no new generations. Source: `results/mcq_secondary_hf.json`.

| Secondary check (all 50 items; invalid = miss) | Base | Fine-tuned |
|---|---|---|
| Loose match: marked option contains SciQ's answer or is contained in it | 0.12 | 0.28 |
| Marked option appears word for word in the passage | 0.26 | 0.7 |

The second check shows the answer is taken from the text. It does not show that the question fits the answer.

## Intended use and limits

- **Intended use:** answering a student's question from given lecture excerpts, in the AI Study Buddy app. Non-commercial (SciQ licence).
- **Domain:** trained on school-level science passages, not on lecture transcripts. Transfer to transcripts was measured in Phase 11 on the golden set `ci_lecture` (one CI lecture, 12 answerable + 8 unanswerable questions, judge `qwen/qwen3.8-27b`, 2026-11-09): fine-tuned vs base faithfulness 0.917 vs 0.724, hallucination rate 0.083 vs 0.929, correctness 0.375 vs 0.625, refusal accuracy 0.75 vs 0.50 (details: `docs/finetuning.md` §4 and `docs/llmops_results.md` §8). The fine-tuned model stays closer to the excerpts but often answers incompletely.
- **Length:** trained on prompts up to 1,024 tokens; the app's prompts can be longer (Modelfile `num_ctx 4096`).
- **Behaviour:** it can still be wrong, and it can refuse answerable questions or answer unanswerable ones (see the refusal confusion above).
- **MCQ:** not reliable enough to use without validation (duplicate options, above).
- **What the app adds:** it refuses before calling the model when retrieval scores are low, checks citations, and takes timestamps from the transcript, never from the model.

## How to use

```bash
ollama create study-buddy-qwen -f Modelfile     # GGUF next to the Modelfile
```

The prompt format is in `prompts.py` (`rag_answer@v1` + JSON schema). The GGUF carries the Qwen3 chat template
with thinking off (Ollama uses the template inside the GGUF); the Modelfile sets temperature 0.1.
