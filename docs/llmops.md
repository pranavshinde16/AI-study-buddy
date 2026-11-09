# LLMOps: metrics, monitoring and evaluation (Phase 11)

This page explains **what is measured, how, and where to see it**. It contains no results: the numbers live in
the database and are exported to [llmops_results.md](llmops_results.md) by a script, never written by hand.
Endpoints: [api.md](api.md#llmops-phase-11).

## 1. Where the data comes from

Every request to a model goes through one of three wrappers (`services/llm/client.py`, `services/asr/client.py`,
`services/embeddings.py`), and each request writes a row. Nothing is sampled or estimated.

| Table | One row per | Used for |
|---|---|---|
| `llm_calls` | request sent to a model (LLM, speech-to-text, embedding), including retries and JSON repairs | latency per task, tokens, cost, errors, prompt versions, model versions |
| `pipeline_runs` | pipeline stage of a lecture (with `audio_sec`) | transcription time and real-time factor |
| `qa_logs` | `/ask` or `/chat` question (answered, refused or failed) | end-to-end question latency, refusals by layer |
| `eval_runs`, `eval_items` | evaluation run / question | retrieval, faithfulness, correctness, refusal accuracy |

The dashboard (**LLMOps** page) and `/api/llmops/*` compute everything from these rows when you open them.
Evaluation traffic is logged under tasks starting with `eval_` and is **excluded** from the live-traffic metrics
unless you tick "Include eval traffic".

## 2. Metrics

| # | Metric | Definition | Where |
|---|---|---|---|
| M1 | Transcription time, **real-time factor** | `transcribing` stage duration ÷ audio seconds. Below 1 is faster than real time. Pooled = total processing ÷ total audio | KPI card, Transcription table |
| M2–M3 | Summary / quiz (and every task's) latency | p50 and p95 of **successful** requests (`status = ok`) per task and model. Percentiles use linear interpolation between ranks | Latency chart "By task" |
| M4 | Question latency, end to end | `qa_logs.latency_ms`: from the request to the answer, including retrieval, per generator; split into answered / refused by model / refused by threshold | Latency chart "By generator" |
| M5 | Tokens and cost | Sums of `input_tokens` / `output_tokens` per task, lecture and day. **Actual cost** is what was billed (`$0` on Groq's free tier and for local models). **Equivalent cost** prices the same tokens with the reference list prices in `backend/config/pricing.yaml`; speech-to-text is priced per audio minute from `pipeline_runs`. A model without a listed price is counted as *unpriced*, never guessed | KPI card, Tokens and cost |
| + | Error rate and JSON parse-failure rate | Failed = `error`, `unavailable`, `rate_limited` or `not_configured`. Parse failure = `json_invalid` (the client then makes one repair request; "after repair" means the user got `502 LLM_OUTPUT_INVALID`) | KPI card, Errors table |
| + | Refusals by layer | From `qa_logs.refusal_reason`: `below_threshold` (best retrieval score below `RAG_MIN_SCORE`, no LLM call) vs `not_in_chunks` (the model said the excerpts don't answer it) | Answers and refusals chart |
| M6 | Retrieval quality | On the golden set, see §4 | Golden-set evaluation |
| M7 | Faithfulness / hallucination rate | LLM-as-judge, see §4 | Golden-set evaluation |
| M8 | Refusal accuracy | Share of unanswerable golden questions that were refused, overall and split by layer | Golden-set evaluation |

**Prompt versions.** Every call logs `prompt_id@version`. The *Prompt versions* table shows latency, failure rates
and mean tokens per version, so a prompt change (which must bump the version) can be compared with the previous one.

**Model versions.** `llm_calls.model_version` stores what actually answered:
- Groq / OpenAI: the model string returned in the response.
- Ollama: `<tag>@sha256:<digest>`, read from Ollama's `GET /api/tags` (cached 5 minutes). Rebuilding a model with
  `ollama create` changes the digest, so old and new builds stay distinguishable.
- Embeddings: `BAAI/bge-small-en-v1.5@<Hugging Face commit>` of the local copy.
- Groq speech-to-text returns no model string, so those rows keep `null`.

The **model registry** (`/api/llmops/models`) adds, for the fine-tuned model, its provenance from
`finetune/results/training.json`: base model and revision, dataset and revision, LoRA settings, GGUF file and size,
and the Hub repo (`FINETUNED_HUB_REPO`).

## 3. The golden set

Hand-written questions about one lecture, in `backend/eval/golden/<name>.jsonl`; the format and the current sets
are described in [backend/eval/golden/README.md](../backend/eval/golden/README.md). Each line has `id`, `question`,
`answerable`, `gold_start` / `gold_end` (seconds where the lecture answers it), `reference_answer`, `kind`
(`on_topic`, `near_topic`, `off_topic`) and optionally `difficulty`. **The team writes the questions and labels;
no model generates them.**

```
cd backend
python -m eval.validate --set ci_lecture --lecture-id <uuid>   # checks the file, and times against the lecture
python -m eval.segments --lecture-id <uuid> --segments              # transcript with times, to check alignment
python -m eval.run --set ci_lecture --lecture-id <uuid> --generator cloud --limit 3   # smoke test
python -m eval.run --set ci_lecture --lecture-id <uuid> --generator all
python -m eval.import_offline                                       # Phase 10 SciQ results as offline runs
python -m scripts.export_llmops                                     # regenerate docs/llmops_results.md
```

The same commands work in PowerShell and in bash/zsh (run them from `backend/` with the virtual environment active).

## 4. The evaluation harness (`python -m eval.run`)

For one golden set on one lecture the harness writes **one retrieval run** and **one run per generator**:

1. **Retrieval (M6), reported once**, because every generator uses the same retriever. Each question is embedded
   exactly as `/ask` does (bge query prefix, top-k = `RAG_TOP_K`). For each answerable question, a retrieved chunk is
   *relevant* when its time range overlaps `[gold_start, gold_end]`:
   - **Hit@k** (k = 1, 3, `RAG_TOP_K`): a relevant chunk is in the top k.
   - **MRR**: mean of 1 / rank of the first relevant chunk (0 when none).
   - **Context precision**: relevant chunks ÷ retrieved chunks.
   - **Average precision**: rank-weighted context precision (mean precision@i over the ranks holding a relevant chunk).
2. **Each generator** (`cloud`, `finetuned`, `base`) answers every question through the real `RagService.answer`
   path (threshold, prompt `rag_answer@v1`, citation check). Then:
   - **Refusal accuracy (M8)**: unanswerable questions that were refused, split into refused by the threshold and
     by the model, and per `kind` (near-topic is the hard case). **False refusals**: answerable questions that were
     refused. **Decision accuracy**: answer-vs-refuse decisions that match the label, over all questions.
   - **Faithfulness (M7)**: for every answered question, the judge (prompt `eval_faithfulness@v1`) splits the answer
     into atomic claims and checks each one against **the chunks the model was given**. Faithfulness = supported ÷
     total claims; the **hallucination rate** is the share of judged answers with faithfulness below 1.
   - **Correctness**: for answered, answerable questions, the judge (prompt `eval_correctness@v1`) compares the answer
     with `reference_answer` and gives **1** (essential information present), **0.5** (partly right, e.g. one part of a
     multi-part question missing) or **0**. Reported as the mean over answered questions, and over all answerable
     questions with a refusal counted as 0.
   - **Latency**: end-to-end per question (p50/p95).
3. **RAG_MIN_SCORE check**: the retrieval run also reports the top score of every question by `kind`, how many
   answerable questions the current threshold would refuse on its own, and how many unanswerable ones it refuses
   vs passes to the model. It describes; it does **not** change the threshold (that stays a team decision).

The judge is `EVAL_JUDGE_MODEL` (default `qwen/qwen3.8-27b` on Groq; `llama-3.3-70b-versatile` was the first choice but Groq no longer offered it on 2026-11-09), deliberately **a different model from
the cloud generator** (`LLM_MODEL`, gpt-oss-120b). Judge calls are logged as `eval_judge_*` tasks with temperature 0.

**Free tier.** All calls go through the same client, so they share the Groq pacer (`GROQ_TOKENS_PER_MINUTE`) and
retry on 429 with backoff, on the same provider only. A full run is slow on purpose; the harness prints one line per
question and saves each item as it finishes, so an interrupted run keeps its items (the run is marked `failed`).
If a generator's model is unavailable on the first question (for example Ollama not running), that generator's run
stops with `MODEL_UNAVAILABLE` instead of failing every question.

**Offline runs.** `python -m eval.import_offline` copies the per-model summaries of `finetune/results/eval_hf.json`
(500 SciQ test items, Colab GPU) and `eval_ollama_subset50.json` (50-item subset through Ollama on CPU) into
`eval_runs` with `source = offline_import`, unchanged, so the dashboard shows the SciQ results next to the lecture
results. Importing twice is a no-op.

## 5. Limitations

- **LLM-as-judge bias.** A judge model can favour fluent or longer answers and can be lenient or strict in ways a
  human would not be. Using a different model from the cloud generator avoids the most direct *self-judging* bias,
  but the judge and generator are both large instruction-tuned models and may share blind spots. The local
  `finetuned` / `base` models are judged by the same judge, so the comparison between generators is consistent, but
  absolute faithfulness and correctness values should be read with that caveat. A human check of a sample of
  judged items is the safeguard; every claim and verdict is stored in `eval_items.metrics_json` for that purpose.
- **Small golden sets.** About 20–30 questions on one lecture give noisy rates (one question moves a rate by several
  points). Report the counts next to the rates.
- **Retrieval labels are time ranges.** A chunk counts as relevant when it overlaps the gold range, even if the
  overlap is small, and Hit@k can't tell whether the chunk contains the whole answer.
- **Equivalent cost** uses reference list prices that change over time (`pricing.yaml` has a `checked` date) and
  excludes models with no published price (they are shown as unpriced).
- **System-wide metrics.** Every logged-in user sees the same metrics (single-team demo). A multi-tenant deployment
  would filter by `user_id`.
- **Latency depends on the machine and on the free tier.** The local models run on CPU, and the Groq pacer can add
  waits that are counted in end-to-end latency (but not in a single request's latency).
