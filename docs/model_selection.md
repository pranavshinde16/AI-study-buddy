# Model selection

Why each model was chosen, judged on four criteria: **accuracy** (measured where we have a measurement), **cost**,
**free tier** and **integration** effort. Every measured number here is copied from a results file or the generated
[llmops_results.md](llmops_results.md), and the source is named next to it. What each model does in the app:
[ai_mapping.md](ai_mapping.md).

**Project decision (Nov 2026): free tiers by default.** Groq serves both speech recognition and the LLM. OpenAI is
optional, used only when `ASR_PROVIDER=openai` or `LLM_PROVIDER=openai` is set, and the app **never falls back to a
paid provider on its own**. Over all logged live traffic the actual cost was **$0.000000**; the same tokens at the
reference list prices in `backend/config/pricing.yaml` would have cost $0.048353 ([llmops_results.md](llmops_results.md) §1).

## 1. Summary

| Need | Chosen | Main alternatives | Deciding reasons |
|---|---|---|---|
| Speech recognition | Groq **whisper-large-v3-turbo** | local faster-whisper, OpenAI `whisper-1` | free, very fast, segment timestamps, OpenAI-compatible API |
| LLM (summary, notes, quiz, flashcards, grading, RAG answers) | Groq **openai/gpt-oss-120b** | `gpt-5-mini` (paid), `openai/gpt-oss-20b` | free, JSON output, strong grounded answers on our golden set |
| Embeddings | **BAAI/bge-small-en-v1.5** (local) | all-MiniLM-L6-v2, OpenAI `text-embedding-3-small` | free, CPU, good retrieval for its size |
| Vector database | **ChromaDB** (embedded, persistent) | FAISS | metadata filter by lecture, persistence, no extra server |
| Small language model to fine-tune | **Qwen3-1.7B** | Llama-3.2-1B-Instruct, SmolLM2-1.7B | fits a free Colab T4 with QLoRA, Apache-2.0, GGUF for Ollama |
| Fine-tuning library | **Unsloth + TRL + PEFT** | plain Transformers + PEFT | faster and lighter on a T4 |
| SLM serving | **Ollama** (GGUF q4_k_m) | Transformers inside FastAPI | runs on a laptop CPU, OpenAI-compatible API, so no new client code |
| Evaluation judge | Groq **qwen/qwen3.8-27b** | llama-3.3-70b-versatile (first choice) | free, and a different model family from the cloud generator |

## 2. Each choice

### Speech recognition: Whisper large-v3-turbo on Groq

- **Accuracy:** Whisper large-v3-turbo is a strong general-purpose English model. **We did not measure word error
  rate** on our lectures: TBD (no reference transcript was made). Transcripts were checked by hand during the
  golden-set alignment (Phase 11).
- **Speed (measured):** pooled real-time factor **0.0078** over 6 transcriptions; for example, a 648.8 s lecture
  was transcribed in 4.84 s ([llmops_results.md](llmops_results.md) §2).
- **Cost / free tier:** $0 on Groq's free tier. OpenAI's API would be paid per minute.
- **Integration:** an OpenAI-compatible endpoint that returns segment start/end times (`verbose_json`), which the
  grounding rules need. The same adapter serves OpenAI when someone opts in. Local `faster-whisper` is the offline
  option (slower on CPU, optional `requirements-asr-local.txt`).

### LLM: openai/gpt-oss-120b on Groq

- **Accuracy (measured on the golden set `ci_lecture`, 20 questions, judge qwen/qwen3.8-27b):** faithfulness 1,
  hallucination rate 0, correctness 0.8333, refusal accuracy 1, decision accuracy 1 ([llmops_results.md](llmops_results.md) §8).
  It is the best of the three generators on every quality metric there.
- **JSON reliability (measured):** 0 JSON parse failures over 194 live calls ([llmops_results.md](llmops_results.md) §1).
- **Speed (measured):** p50 latency per request between 568.1 ms (rag_rewrite) and 2,475.3 ms (quiz) ([llmops_results.md](llmops_results.md) §3).
- **Cost / free tier:** $0. `gpt-5-mini` was the original design default but is paid; it remains available with
  `LLM_PROVIDER=openai` and is never used automatically.
- **Integration:** an open-weight model on the same OpenAI-compatible API as Whisper, so one SDK and one client
  cover both. `reasoning_effort=low` is sent to keep hidden reasoning tokens (which count against the free-tier
  token limit) down.

### Embeddings: BAAI/bge-small-en-v1.5

- **Accuracy (measured):** on the golden set, hit@1 0.75, hit@3 1, hit@5 1, MRR 0.875 over 12 answerable
  questions ([llmops_results.md](llmops_results.md) §8). It separates unrelated questions (top scores 0.362–0.519)
  from the lecture's own (0.620–0.760), but not near-topic questions (0.598–0.624) ([rag.md](rag.md#3-calibrating-rag_min_score)).
- **Speed (measured):** p50 32.8 ms per search query on CPU ([llmops_results.md](llmops_results.md) §3).
- **Cost / free tier:** free, runs locally; no API limit.
- **Integration:** sentence-transformers, about 130 MB download, 384-dimension vectors, loaded once on first use.
  bge's query prefix is applied to questions only.

### Vector database: ChromaDB

- Filters by `lecture_id` metadata in the query, stores data on disk, and needs no extra server in development
  (a folder) or in Docker (a volume). FAISS is faster at scale but has no metadata filtering or persistence built in.

### Small language model: Qwen3-1.7B, fine-tuned with QLoRA on SciQ

- **Accuracy (measured, 500 SciQ test items, `finetune/results/eval_hf.json`):** grounded-QA accuracy 0.7227 → **0.9093**
  after fine-tuning; refusal precision 0.4737 → 0.9221; token F1 0.3535 → 0.8339. Regressions: MCQ JSON validity
  0.9 → 0.82 and GPU latency (details: [finetuning.md](finetuning.md)).
- **On lecture text (golden set):** faithfulness 0.9167 and hallucination rate 0.0833, but correctness only 0.375
  (base: 0.7241, 0.9286, 0.625) ([llmops_results.md](llmops_results.md) §8).
- **Cost / free tier:** trained on a free Colab T4 in about **30.2 min (reconstructed)**
  (`finetune/results/training_time_reconstructed.json`); served locally for $0.
- **Integration:** 1.7B parameters fit 4-bit QLoRA on a T4; Apache-2.0; exports to GGUF for Ollama, which the
  app's LLM client calls through the same OpenAI-compatible interface as Groq.
- **Trade-off:** on CPU through Ollama an answer takes about 10 s (mean 9,877.2 ms on the 50-item subset,
  `finetune/results/eval_ollama_subset50.json`), versus under a second for the cloud model.

### Evaluation judge: qwen/qwen3.8-27b on Groq

- A judge from a different model family than the cloud generator avoids the most direct self-judging bias.
- The first choice, `llama-3.3-70b-versatile`, returned `404 model_not_found` from Groq on 2026-11-09, so the team
  chose qwen. Its price was not verified, so it is counted as *unpriced* in the cost metrics.

## 3. Free-tier limits we hit, and what we changed

| Limit (as published by Groq, checked 2026-11-06) | What happened | What we changed |
|---|---|---|
| gpt-oss-120b: 30 requests/min, 1K requests/day, **8K tokens/min**, 200K tokens/day | A 60-minute transcript (about 13k tokens) cannot go in one request. Map-reduce calls in a row would exceed 8K tokens in a minute | Single-pass summaries only up to 3,500 tokens, longer lectures in windows of ≤ 2,500 tokens (`SUMMARY_*`); client-side token pacer (`GROQ_TOKENS_PER_MINUTE=8000`) |
| 8K tokens/min (pacer) | The pacer waited 54.5 s before a summary call in a map-reduce test (Phase 5) and 57.3 s before a chat answer (Phase 7); the cloud generator's p95 latency in the evaluation was 56,849.2 ms because of these waits ([llmops_results.md](llmops_results.md) §8) | Accepted: waiting is better than a 429. The UI shows "Waiting for the free-tier rate limit…" on slow requests |
| 429 responses | **0** rate-limited calls reached the user over all live traffic ([llmops_results.md](llmops_results.md) §6) | Backoff with `Retry-After` on the same provider; `429 RATE_LIMITED` if it still fails; never a paid fallback |
| Whisper: **25 MB per file**, 20 requests/min, 2K/day, 7,200 audio-seconds/hour | Lecture recordings are larger than 25 MB | ffmpeg converts to 16 kHz mono FLAC and cuts 10-minute pieces of at most 24 MB, then shifts timestamps |
| Model availability | Llama 3.x models were listed as "Contact Sales" and `llama-3.3-70b-versatile` returned 404 during the evaluation | Judge switched to qwen/qwen3.8-27b; unknown or retired models return `503 MODEL_UNAVAILABLE` |
| Colab free T4 (16 GB) | Limited session time; the T4 has no native bf16 tensor cores (PyTorch reports bf16 as supported, but it is emulated) | fp16 (`training.json`: fp16 true, bf16 false), 4-bit QLoRA, one epoch on 3,000 examples, checkpoints saved to Google Drive |

The limits above are the published free-tier limits at the time we checked; they change, so check them again before
relying on them.
