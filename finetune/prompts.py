"""Prompts shared by prepare_data.py, the Colab notebook and evaluate.py, so training, evaluation
and the app all use the same text.

RAG_ANSWER_* is a verbatim copy of what the app sends to an answer generator: the system prompt of
backend/app/prompts/rag_answer.yaml (v1) plus the JSON-schema instruction the LLM client appends
for RagAnswerOut. tests/test_prompt_sync.py fails if the app's prompt changes and this copy doesn't.

MCQ_GEN_* is fine-tuning-only (the app writes quizzes with the cloud model), versioned here.

Qwen3 thinking mode is OFF everywhere: training and evaluation render prompts with
`enable_thinking=False`, which ends the generation prompt with an empty think block
(ASSISTANT_PREFIX); the Ollama Modelfiles insert the same block.
"""

from __future__ import annotations

import json
from string import Template

RAG_ANSWER_ID = "rag_answer"
RAG_ANSWER_VERSION = "v1"  # must equal backend/app/prompts/rag_answer.yaml `version`
RAG_ANSWER_TEMPERATURE = 0.1  # the app's value for this prompt

RAG_ANSWER_SYSTEM = (
    "You are a study assistant who answers students' questions about one lecture, using ONLY the\n"
    "numbered transcript excerpts below.\n"
    "\n"
    "Rules:\n"
    "- Use only what the excerpts say. Do not add facts, examples or explanations from outside\n"
    "  knowledge, even if you know them.\n"
    "- If the excerpts do not contain the answer (the question is about something else, or the\n"
    "  lecture only mentions it without answering), set \"answerable\" to false and say briefly that\n"
    "  the lecture doesn't cover it. Do not guess.\n"
    "- If they answer it only partly, answer that part, set \"answerable\" to true and say what the\n"
    "  lecture doesn't cover.\n"
    "- Cite the excerpts you used inline as [C1], [C2] ... and list the same ids in \"citations\".\n"
    "  Never cite an id that is not in the list below.\n"
    "- Never write clock times or timestamps; the app adds them from the cited excerpts.\n"
    "- Answer in 1-5 sentences, clearly, for a student revising the lecture.\n"
    "- The excerpts come from speech recognition and may contain recognition errors; keep the\n"
    "  lecturer's meaning.\n"
)

# Appended by backend/app/services/llm/client.py::_schema_instruction(RagAnswerOut).
RAG_ANSWER_SCHEMA_INSTRUCTION = (
    "\n\nRespond with a single JSON object only (no markdown, no commentary) that validates "
    "against this JSON Schema:\n"
    '{"properties":{"answerable":{"description":"false if the excerpts do not answer the question",'
    '"title":"Answerable","type":"boolean"},"answer":{"title":"Answer","type":"string"},'
    '"citations":{"description":"excerpt ids used, e.g. [\\"C1\\", \\"C3\\"]","items":{"type":"string"},'
    '"title":"Citations","type":"array"}},"required":["answerable","answer"],"title":"RagAnswerOut",'
    '"type":"object"}'
)

RAG_ANSWER_USER = Template("Lecture title: ${title}\n\nQuestion: ${question}\n\nTranscript excerpts:\n${chunks}\n")

# SciQ has no lecture; every example uses this title (the app sends the real lecture title).
SCIQ_TITLE = "Science lesson"

# The refusal the model learns; the app replaces refusals with its own standard text anyway.
REFUSAL_ANSWER = "The lecture doesn't cover this question."

MCQ_GEN_ID = "mcq_gen"
MCQ_GEN_VERSION = "v1"
MCQ_GEN_SYSTEM = (
    "You write multiple-choice questions for students from a short study passage.\n"
    "\n"
    "Rules:\n"
    "- Use only facts stated in the passage.\n"
    "- Write exactly one question with 4 options: one correct answer and 3 plausible but wrong\n"
    "  distractors.\n"
    "- Respond with a single JSON object only (no markdown, no commentary):\n"
    '  {"question": string, "options": [4 strings], "answer": "A" | "B" | "C" | "D"}'
)
MCQ_GEN_USER = Template("Passage:\n${passage}\n")

LETTERS = ("A", "B", "C", "D")

# What Qwen3's chat template appends after "<|im_start|>assistant\n" when enable_thinking=False.
ASSISTANT_PREFIX = "<think>\n\n</think>\n\n"
# Marker before the trained (assistant) tokens: only the answer after the empty think block is learned.
RESPONSE_MARKER = "<|im_start|>assistant\n" + ASSISTANT_PREFIX
INSTRUCTION_MARKER = "<|im_start|>user\n"


# Chat template embedded in BOTH Ollama GGUFs (fine-tuned and base). Ollama 0.40 renders Qwen3 with the
# GGUF's own Jinja template ("template source: gguf_chat_template") and ignores a Modelfile TEMPLATE,
# and Qwen3's original template thinks unless the client sends enable_thinking=false, which the app's
# OpenAI-compatible calls can't. This template ALWAYS ends the generation prompt with the empty think
# block, so the served prompt is byte-identical to training's apply_chat_template(..., enable_thinking=False)
# for the app's [system, user] messages (checked against the real tokenizer; see the README).
NO_THINK_CHAT_TEMPLATE = (
    "{%- for message in messages %}"
    "{{- '<|im_start|>' + message['role'] + '\\n' + message['content'] + '<|im_end|>' + '\\n' }}"
    "{%- endfor %}"
    "{%- if add_generation_prompt %}"
    "{{- '<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n' }}"
    "{%- endif %}"
)


def rag_system() -> str:
    return RAG_ANSWER_SYSTEM + RAG_ANSWER_SCHEMA_INSTRUCTION


def format_excerpts(texts: list[str]) -> tuple[str, list[str]]:
    """Same layout as backend/app/services/rag.py: "[C1] text" blocks separated by a blank line."""
    labels = [f"C{i + 1}" for i in range(len(texts))]
    return "\n\n".join(f"[{lbl}] {t.strip()}" for lbl, t in zip(labels, texts)), labels


def rag_messages(question: str, excerpts: list[str], title: str = SCIQ_TITLE) -> list[dict[str, str]]:
    chunks, _ = format_excerpts(excerpts)
    user = RAG_ANSWER_USER.substitute(title=title, question=question.strip(), chunks=chunks)
    return [{"role": "system", "content": rag_system()}, {"role": "user", "content": user}]


def mcq_messages(passage: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": MCQ_GEN_SYSTEM},
        {"role": "user", "content": MCQ_GEN_USER.substitute(passage=passage.strip())},
    ]


def rag_target(answerable: bool, answer: str, citations: list[str]) -> str:
    """Assistant JSON in RagAnswerOut field order."""
    return json.dumps({"answerable": answerable, "answer": answer, "citations": citations}, ensure_ascii=False)


def mcq_target(question: str, options: list[str], answer_letter: str) -> str:
    return json.dumps({"question": question, "options": options, "answer": answer_letter}, ensure_ascii=False)


PROMPT_VERSIONS = {
    "rag_answer": f"{RAG_ANSWER_ID}@{RAG_ANSWER_VERSION}",
    "mcq_gen": f"{MCQ_GEN_ID}@{MCQ_GEN_VERSION}",
}
