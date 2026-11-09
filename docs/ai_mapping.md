# AI categories, subtasks and models

The app uses **two AI categories**, **Speech Recognition** and **Natural Language Processing**, split into
**7 subtasks** plus one domain fine-tune. Each row names the model that runs in the finished app, the code that
calls it and the feature it powers. Why each model was chosen: [model_selection.md](model_selection.md).

Every call to any of these models goes through one of three wrappers (`services/llm/client.py`,
`services/asr/client.py`, `services/embeddings.py`) and is logged to `llm_calls` ([llmops.md](llmops.md)).

## 1. Subtask map

| # | Subtask | Category | Model / API (as deployed) | Code | Feature it powers |
|---|---|---|---|---|---|
| 1 | Automatic speech recognition | Speech Recognition | **Whisper large-v3-turbo** on the Groq API (free tier), `verbose_json` with segment timestamps. Options: local `faster-whisper`, or OpenAI `whisper-1` (paid, opt-in only) | `services/asr/`, `services/media.py`, `workers/pipeline.py` | Transcript page: timestamped segments, search, TXT/SRT/VTT download, media player that seeks to a segment |
| 2 | Abstractive summarization | NLP | **`openai/gpt-oss-120b`** (open-weight) on the Groq API; prompt `summary@v1`, map-reduce over windows for long lectures | `services/generation/summary.py`, `services/summaries.py` | Summary & Notes page: summary, key takeaways, revision notes |
| 3 | Question generation | NLP | `openai/gpt-oss-120b` on Groq, JSON output; prompt `quiz@v1`; app-side validation and regeneration | `services/generation/quiz.py`, `services/quizzes.py` | Quiz page: MCQ, true/false and short-answer questions at three difficulty levels, with explanations and "jump to timestamp" |
| 4 | Question answering (RAG) | NLP | Retriever: bge-small + ChromaDB. Generator: `gpt-oss-120b` (**cloud**), the fine-tuned **study-buddy-qwen** (Qwen3-1.7B + LoRA) or the **base** Qwen3-1.7B, both through Ollama; prompts `rag_answer@v1`, `rag_rewrite@v1` | `services/rag.py`, `services/chat.py`, `services/llm/generators.py` | Ask page: grounded answers with timestamped source chips, "not in lecture" refusals, multi-turn chat, model switch |
| 5 | Text generation | NLP | `openai/gpt-oss-120b` on Groq; prompts `notes@v1`, `flashcards@v1`, `grade_short@v1` | `services/generation/summary.py`, `services/generation/flashcards.py`, `services/grading.py` | Topic-wise notes and definitions glossary; flashcard deck; written feedback on short answers |
| 6 | Semantic embeddings / similarity | NLP | **`BAAI/bge-small-en-v1.5`** (sentence-transformers, local CPU, 384 dimensions) | `services/embeddings.py`, `services/indexing.py`, `services/vectorstore.py`, `services/grading.py` | Chunk indexing and retrieval for Ask; similarity fallback that grades short answers when the LLM grader is unavailable; retrieval metrics in the evaluation |
| 7 | Information / keyphrase extraction | NLP | `openai/gpt-oss-120b` on Groq, JSON output; prompt `topics@v1` (plus the definitions in `summary@v1`) | `services/generation/summary.py`, `services/generation/quiz.py` | Topic segmentation with start/end times (the notes accordion), key terms for the glossary, the topic tag on every quiz question and flashcard, which drives topic mastery and weak topics |
| + | Domain fine-tuning | NLP | **Qwen3-1.7B** + QLoRA (Unsloth) on **SciQ**, served as GGUF q4_k_m through Ollama | `finetune/`, generator `finetuned` | The "Fine-tuned SLM" option on the Ask page; base-vs-fine-tuned comparison on the LLMOps page |
| + | Evaluation judge | NLP | `qwen/qwen3.8-27b` on Groq (deliberately a different model from the cloud generator); prompts `eval_faithfulness@v1`, `eval_correctness@v1` | `services/evaluation/judge.py` | Faithfulness and correctness in the golden-set evaluation ([llmops.md](llmops.md#4-the-evaluation-harness-python--m-evalrun)) |

**Grounding rules shared by subtasks 2–5 and 7:** the model sees only the transcript (or the retrieved chunks),
it refers to transcript segment ids and never writes times, and every timestamp shown in the app comes from the ASR
segments. Details: [architecture.md](architecture.md#4-grounding-rules-how-the-app-avoids-invented-content).

**Planned in the original design but not built** (Phase 9, see [architecture.md](architecture.md#12-not-built-phase-9-future-work)):
the mind map (concept relations, subtask 7) and adaptive difficulty / recommendations.

## 2. Hugging Face integration map

| Hugging Face asset | What it is | Where the app or project uses it | Pinned version / evidence |
|---|---|---|---|
| [`BAAI/bge-small-en-v1.5`](https://huggingface.co/BAAI/bge-small-en-v1.5) via **sentence-transformers** | Embedding model (384-d) | Downloaded from the Hub on first use and run locally on CPU for indexing, retrieval and the grading fallback (`services/embeddings.py`); cached in the `hf-cache` Docker volume | Revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, logged in `llm_calls.model_version` ([llmops_results.md](llmops_results.md) §7) |
| [`allenai/sciq`](https://huggingface.co/datasets/allenai/sciq) via **Datasets** | 13.7k science exam questions with support paragraphs (CC-BY-NC-3.0) | Training, validation and test data for the fine-tune (`finetune/prepare_data.py`) | Revision `2c94ad3e1aafab77146f384e23536f97a4849815` (`finetune/results/data_stats.json`) |
| [`unsloth/Qwen3-1.7B`](https://huggingface.co/unsloth/Qwen3-1.7B) | Base small language model (Apache-2.0) | Base model for QLoRA; the same weights with the adapter off are the "base" generator | Revision `6262b50d6c1f8ee5e4ac750d710c33603bfc2a0c` (`finetune/results/training.json` → `config`) |
| **Transformers**, **PEFT**, **TRL**, **Unsloth**, **bitsandbytes**, **Accelerate** | Training stack | 4-bit loading, LoRA adapter (r = 16, alpha = 16, attention + MLP projections), `SFTTrainer` on assistant tokens, GGUF export (`finetune/sciq_finetune_colab.ipynb`) | transformers 5.17.0, peft 0.21.2, trl 1.15.0, unsloth 2026.10.8, bitsandbytes 0.50.2, accelerate 1.15.0, datasets 4.8.5, huggingface_hub 1.33.0 (`training.json` → `versions`) |
| **Hugging Face Hub** repo [`TusharDecoded/study-buddy-qwen3-1.7b-sciq-lora`](https://huggingface.co/TusharDecoded/study-buddy-qwen3-1.7b-sciq-lora) | Published fine-tune (**private**) | Holds the LoRA adapter, the GGUF q4_k_m and the model card ([finetune/MODEL_CARD.md](../finetune/MODEL_CARD.md)); the app loads the GGUF through Ollama | GGUF 1,107,404,864 bytes (`training.json` → `exports.gguf_bytes`); Ollama digest `3e5db5df9364` |
| Open-weight models on the Hub, **hosted by Groq** | `openai/whisper-large-v3-turbo`, `openai/gpt-oss-120b` | Called through Groq's OpenAI-compatible API, not downloaded; listed here because the weights are published on the Hub | Model strings logged per call in `llm_calls` |

`FINETUNED_HUB_REPO` (in `.env`) makes the model registry show the Hub repo next to the fine-tuned model; it is
blank by default because the repo is private.
