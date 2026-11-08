"""The fine-tune prompts must be exactly what the app sends to the 'finetuned'/'base' generators,
and the Modelfiles must render the same Qwen3 thinking-off template the training used."""

import re
from pathlib import Path

import pytest

import prompts

FT = Path(__file__).resolve().parents[1]


def _app():
    pytest.importorskip("pydantic")
    try:
        from app.services.llm.client import _schema_instruction
        from app.services.llm.prompts import PromptRegistry
        from app.services.rag import RagAnswerOut
    except Exception as exc:  # backend venv not active
        pytest.skip(f"backend not importable: {exc}")
    return PromptRegistry().get("rag_answer"), _schema_instruction, RagAnswerOut


def test_rag_prompt_matches_the_app():
    tpl, schema_instruction, RagAnswerOut = _app()
    assert tpl.version == prompts.RAG_ANSWER_VERSION
    assert tpl.temperature == prompts.RAG_ANSWER_TEMPERATURE
    variables = {"title": "Week 1", "question": "What is FaaS?", "chunks": "[C1] a\n\n[C2] b"}
    system, user = tpl.render(variables)
    assert prompts.rag_system() == system + schema_instruction(RagAnswerOut)
    assert prompts.RAG_ANSWER_USER.substitute(variables) == user


def test_excerpts_use_the_app_layout():
    text, labels = prompts.format_excerpts([" first ", "second"])
    assert text == "[C1] first\n\n[C2] second" and labels == ["C1", "C2"]
    msgs = prompts.rag_messages("Why?", ["x"], title="T")
    assert msgs[1]["content"] == "Lecture title: T\n\nQuestion: Why?\n\nTranscript excerpts:\n[C1] x\n"


@pytest.mark.parametrize(("name", "gguf"), [("Modelfile", "study-buddy-qwen-q4_k_m.gguf"),
                                           ("Modelfile.base", "study-buddy-qwen-base-q4_k_m.gguf")])
def test_modelfiles_use_a_local_gguf_and_no_template(name, gguf):
    text = (FT / name).read_text(encoding="utf-8")
    assert re.search(rf"^FROM \./{re.escape(gguf)}$", text, re.MULTILINE)
    # Ollama 0.40 ignores TEMPLATE for Qwen3 and uses the GGUF's own template (set_chat_template.py).
    assert not re.search(r"^TEMPLATE", text, re.MULTILINE)
    assert re.search(r"^PARAMETER temperature 0\.1$", text, re.MULTILINE)
    assert re.search(r'^PARAMETER stop "<\|im_end\|>"$', text, re.MULTILINE)


def test_no_think_template_renders_the_training_prompt():
    jinja2 = pytest.importorskip("jinja2")
    msgs = prompts.rag_messages("What is FaaS?", ["a", "b"], title="T")
    out = jinja2.Environment().from_string(prompts.NO_THINK_CHAT_TEMPLATE).render(
        messages=msgs, add_generation_prompt=True, enable_thinking=True)
    expected = ("<|im_start|>system\n" + msgs[0]["content"] + "<|im_end|>\n"
                "<|im_start|>user\n" + msgs[1]["content"] + "<|im_end|>\n" + prompts.RESPONSE_MARKER)
    assert out == expected
