# Fine-tuning (Phase 10): Qwen3-1.7B on SciQ

This folder turns the small open model **Qwen3-1.7B** into the app's **"finetuned"** answer generator.
It's trained on free Google Colab (T4 GPU) and served locally with **Ollama**. The design is in
[IMPLEMENTATION_PLAN.md §8](../IMPLEMENTATION_PLAN.md#8-fine-tuning-plan).

> **No hand-typed numbers.** Every count, score, time and size comes from the files that the notebook
> and `evaluate.py` write to `results/`. Docs and `MODEL_CARD.md` keep `TBD (run X)` placeholders
> until you fill them from those files.

## What's here

| File | What it does |
|---|---|
| `prompts.py` | The prompts used in training, evaluation and the app. The RAG prompt is a **verbatim copy** of what the app sends (`rag_answer@v1` + its JSON schema); a test fails if they drift apart. Thinking mode is off |
| `prepare_data.py` | Downloads SciQ (pinned revision) and builds 3,000 train / 300 validation / 500 test examples (≈75 % grounded QA, 15 % refusal, 10 % MCQ generation, seed 3407, ≤ 1,024 tokens). Writes `results/data_stats.json` |
| `sciq_finetune_colab.ipynb` | The Colab notebook: install → data → 4-bit QLoRA training → adapter / merged / GGUF exports → base vs fine-tuned evaluation → optional Hub push |
| `metrics.py` | Accuracy, token F1, ROUGE-L, refusal precision/recall, JSON validity, latency (pure Python) |
| `eval_runner.py` | Runs the models: in Colab (adapter off = base, on = fine-tuned) or through Ollama |
| `evaluate.py` | The comparison: same 500 test items, same prompts → `results/eval_<backend>.json` + per-item predictions |
| `requirements-colab.txt` | Exact library versions for Colab |
| `Modelfile` | Ollama recipe for the fine-tuned GGUF (temperature 0.1, 4,096-token context) |
| `Modelfile.base` | The same recipe for the base model, so the comparison differs only in the weights |
| `rescore_mcq.py` | Secondary MCQ checks (loose match, answer in passage, why outputs were invalid), re-scored from the saved predictions → `results/mcq_secondary_<backend>.json`. Added after the first results; the strict metric in `eval_*.json` stays primary |
| `output_stats.py` | Output lengths per model and task (and longest output per batch) from the saved predictions → `results/output_stats_<backend>.json`, used to explain latency |
| `set_chat_template.py` | Copies a GGUF with the thinking-off chat template embedded (used by the notebook and for the base model) |
| `requirements-local.txt` | The one library `set_chat_template.py` needs on your PC (`gguf`) |
| `MODEL_CARD.md` | Model card template (placeholders only) |
| `tests/` | Offline tests: data building, metrics, prompt sync with the app, Modelfile template |
| `results/` | Written by the runs (commit these JSON files) |
| `data/` | Generated JSONL (gitignored: derived from SciQ, re-creatable with `prepare_data.py`) |

### What the model learns (all in the app's own format)

| Task | Share | Input | Target |
|---|---|---|---|
| Grounded QA | ≈75 % | the app's RAG prompt: question + excerpts `[C1]…[Ck]` (the SciQ support paragraph + 1–2 paragraphs of other items that don't contain the answer, shuffled) | `{"answerable": true, "answer": "<answer>. <support sentence with the answer> [Cn]", "citations": ["Cn"]}` |
| Refusal | ≈15 % | same prompt, but only paragraphs of *other* items | `{"answerable": false, "answer": "The lecture doesn't cover this question.", "citations": []}` |
| MCQ generation | ≈10 % | a passage | `{"question", "options": [correct + SciQ's 3 distractors], "answer": "A"–"D"}` |

The justification sentence is taken from SciQ's support text, never written by a model.

## Step by step: train on Colab

1. **Copy the code to Drive.** In Google Drive create `MyDrive/study-buddy-finetune/code/` and upload the
   files of this `finetune/` folder into it (at least the `.py` files, `requirements-colab.txt` and `MODEL_CARD.md`),
   so that the path is `MyDrive/study-buddy-finetune/code/prepare_data.py`. Uploading the whole folder
   (`code/finetune/prepare_data.py`) also works; the notebook detects it.
   *Alternative:* if the GitHub repo is public, set `REPO_URL` in step 2 of the notebook instead.
2. **Open the notebook.** Go to <https://colab.research.google.com> → *File → Upload notebook* →
   `sciq_finetune_colab.ipynb`.
3. **Pick the GPU.** *Runtime → Change runtime type → T4 GPU → Save.*
4. **Run all cells in order** (*Runtime → Run all*, or Shift+Enter cell by cell):
   - Step 2 asks for permission to mount Google Drive: allow it.
   - Step 3 installs the pinned libraries (a few minutes). Colab's own torch is kept.
   - Step 4 writes `data/` and `results/data_stats.json` in Drive.
   - Step 6 trains for 1 epoch and saves checkpoints to Drive every 50 steps.
   - Step 7 saves the adapter, the merged model and the GGUF. The GGUF step compiles llama.cpp
     the first time, which takes several minutes.
   - Step 8 runs the evaluation (1,000 generations; it's the slowest step after training).
5. **If Colab disconnects:** reconnect, run steps 1–5 again, then step 6. It resumes from the last
   checkpoint in Drive. Each training session's time is appended to `results/training_sessions.jsonl`
   (also at every checkpoint), and `results/training.json` adds them up (`train_wall_time_s_total`,
   `train_time_complete`). Re-running step 6 after training finished is harmless: it adds a no-op session.
6. **Optional Hub push (step 9):** open Colab's *Secrets* panel (key icon) → add `HF_TOKEN`
   (a Hugging Face *write* token) → enable *Notebook access* → set `HF_REPO` in the cell. The token
   only lives in Colab Secrets; never paste it into a cell or a file.
   The project's repo is [TusharDecoded/study-buddy-qwen3-1.7b-sciq-lora](https://huggingface.co/TusharDecoded/study-buddy-qwen3-1.7b-sciq-lora) (private).
   **Updating the card later** (step 9 uploads the card as it was then): upload the final `MODEL_CARD.md` in
   Colab's *Files* panel, then run in a cell:

   ```python
   from google.colab import userdata
   from huggingface_hub import HfApi
   HfApi(token=userdata.get("HF_TOKEN")).upload_file(
       path_or_fileobj="/content/MODEL_CARD.md", path_in_repo="README.md",
       repo_id="TusharDecoded/study-buddy-qwen3-1.7b-sciq-lora", commit_message="Model card: final results")
   ```

   Links in the card that point into this repository (`../docs/…`, `results/…`) don't resolve on the Hub.
7. **Download the outputs** from `MyDrive/study-buddy-finetune/`:
   - `results/` → this folder's `results/` (then commit the `.json`/`.jsonl` files),
   - `gguf/study-buddy-qwen-q4_k_m.gguf` → this folder (it's gitignored, about 1 GB).

## Use it in the app (Ollama)

Install Ollama from <https://ollama.com/download> (tested with **0.40.11**) and make sure it's running
(`ollama list` answers). Run these from the **repo root**.

**Thinking off, and why there's an extra step.** Ollama 0.40 renders Qwen3 with the chat template stored
*inside the GGUF* (`ollama show <model>` → `template source: gguf_chat_template`) and ignores a `TEMPLATE`
line in a Modelfile. Qwen3's own template thinks unless the client sends `enable_thinking=false`, which
the app's OpenAI-compatible requests can't. So both GGUFs carry `prompts.NO_THINK_CHAT_TEMPLATE`, which renders
the exact training prompt. The notebook already embeds it in the fine-tuned GGUF; for the base model,
`set_chat_template.py` embeds it in a copy of `qwen3:1.7b`'s GGUF.

1. A small venv for the local tool (once):

   | Windows (PowerShell) | macOS / Linux |
   |---|---|
   | `py -3.12 -m venv finetune\.venv; finetune\.venv\Scripts\python -m pip install -r finetune\requirements-local.txt` | `python3 -m venv finetune/.venv && finetune/.venv/bin/python -m pip install -r finetune/requirements-local.txt` |

2. The **base** model (same template, thinking off):

   | Windows (PowerShell) | macOS / Linux |
   |---|---|
   | `ollama pull qwen3:1.7b` | same |
   | `finetune\.venv\Scripts\python finetune\set_chat_template.py --from-ollama qwen3:1.7b finetune\study-buddy-qwen-base-q4_k_m.gguf` | `finetune/.venv/bin/python finetune/set_chat_template.py --from-ollama qwen3:1.7b finetune/study-buddy-qwen-base-q4_k_m.gguf` |
   | `cd finetune; ollama create study-buddy-qwen-base -f Modelfile.base; cd ..` | `(cd finetune && ollama create study-buddy-qwen-base -f Modelfile.base)` |

3. The **fine-tuned** model (after the Colab run; the GGUF goes in `finetune/`):

   | Windows (PowerShell) | macOS / Linux |
   |---|---|
   | `cd finetune; ollama create study-buddy-qwen -f Modelfile; cd ..` | `(cd finetune && ollama create study-buddy-qwen -f Modelfile)` |

4. Check that thinking is off: `ollama show study-buddy-qwen --template` must print the short template that
   ends in `<think>

</think>

`.

5. In your root `.env` (Ollama's URL is already the default `http://localhost:11434/v1`):

   ```
   FINETUNED_MODEL_TAG=study-buddy-qwen
   BASE_SLM_MODEL_TAG=study-buddy-qwen-base
   ```

Restart the backend. On the **Ask** tab, the model picker now answers with `finetuned` and `base`.
If Ollama isn't running or a model is missing, the app shows "Fine-tuned model not available yet"
together with the backend's exact reason. The first answer after starting Ollama is slower because the model loads.

## Evaluate locally through Ollama (CPU latency, optional)

This is the same comparison as the notebook's step 8, but through the serving path the app uses
(JSON mode, one request per item on your CPU). Copy `data/test_eval.jsonl` from Drive into `finetune/data/` first.

| | Windows (PowerShell) | macOS / Linux |
|---|---|---|
| Quick check (10 items) | `backend\.venv\Scripts\python finetune\evaluate.py --items finetune\data\test_eval.jsonl --out finetune\results --limit 10` | `backend/.venv/bin/python finetune/evaluate.py --items finetune/data/test_eval.jsonl --out finetune/results --limit 10` |
| Latency subset (50 items, same task mix, seed 3407) | `backend\.venv\Scripts\python finetune\evaluate.py --items finetune\data\test_eval.jsonl --out finetune\results --subset 50` | `backend/.venv/bin/python finetune/evaluate.py --items finetune/data/test_eval.jsonl --out finetune/results --subset 50` |
| Full run (500 items × 2 models) | same without `--limit 10` | same without `--limit 10` |

The full run writes `results/eval_ollama.json` and `results/predictions_ollama_{base,finetuned}.jsonl`; `--subset 50`
writes `eval_ollama_subset50.json` (with the sampled ids) and `--limit 10` writes `eval_ollama_smoke10.json`.
Each model gets one untimed warm-up request first, so loading the model isn't counted as latency. It uses
only the Python standard library, so any Python 3.11+ works.

## Re-score the saved predictions (no GPU, no model)

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `backend\.venv\Scripts\python finetune\rescore_mcq.py --backend hf` | `backend/.venv/bin/python finetune/rescore_mcq.py --backend hf` |
| `<venv with transformers>\python finetune\output_stats.py --backend hf --tokenizer unsloth/Qwen3-1.7B` | `<venv with transformers>/bin/python finetune/output_stats.py --backend hf --tokenizer unsloth/Qwen3-1.7B` |

Without `--tokenizer`, `output_stats.py` reports only character counts (any Python works).
`results/training_time_reconstructed.json` documents how the training time of the first run was rebuilt (see `MODEL_CARD.md`).

## Tests (offline, no GPU)

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `backend\.venv\Scripts\python -m pytest finetune\tests -q` | `backend/.venv/bin/python -m pytest finetune/tests -q` |

Run them with the backend's venv: `test_prompt_sync.py` imports the app to check that the prompts match.

## Notes and limits

- **Licence:** SciQ is **CC-BY-NC-3.0**, so the fine-tuned model is for non-commercial use (Qwen3 itself is Apache-2.0).
- **Context length:** training examples are at most 1,024 tokens. The app's RAG prompt with 5 transcript
  chunks is longer, so the Modelfiles set `num_ctx 4096`. How well the model transfers to lecture
  transcripts is measured in Phase 11 (golden set), not assumed here.
- **xformers:** it isn't installed (to keep Colab's torch). Unsloth then uses PyTorch attention. If a
  future Unsloth demands it, install the xformers build that matches Colab's torch.
- **Pinned sources:** `allenai/sciq` @ `2c94ad3e1aafab77146f384e23536f97a4849815`, `unsloth/Qwen3-1.7B` @
  `6262b50d6c1f8ee5e4ac750d710c33603bfc2a0c` (in `prepare_data.py`; also written to the result files).
