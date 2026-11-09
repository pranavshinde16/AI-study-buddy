"""Phase 11 model-version tracking and the model registry (no network: fake Ollama tag lists)."""

import json

import pytest

from app.api.deps import get_model_registry_dep
from app.models.llmops import LLMCall
from app.services.embeddings import EmbeddingClient, model_version_of
from app.services.llm.client import LLMClient, supports_reasoning_effort
from app.services.llm.model_info import ModelVersionResolver, OllamaModelInfo, native_root
from app.services.llm.pricing import load_pricing
from app.services.llm.prompts import PromptRegistry
from app.services.model_registry import ModelRegistryService, finetune_details
from tests.fakes import FakeProvider, ok

DIGEST = "a" * 64
TAGS = {"models": [{"name": "study-buddy-qwen:latest", "digest": DIGEST, "size": 1107404864,
                    "modified_at": "2026-11-08T10:00:00Z",
                    "details": {"family": "qwen3", "parameter_size": "2.0B", "quantization_level": "Q4_K_M"}}]}


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_native_root():
    assert native_root("http://localhost:11434/v1") == "http://127.0.0.1:11434"
    assert native_root("http://h:1/v1/") == "http://h:1"


def test_ollama_version_and_caching():
    fetches, clock = [], Clock()
    info = OllamaModelInfo("http://x/v1", fetch=lambda: fetches.append(1) or TAGS, clock=clock)
    assert info.version("study-buddy-qwen", "study-buddy-qwen") == f"study-buddy-qwen@sha256:{DIGEST}"
    assert info.version("missing", None) == "missing"
    assert len(fetches) == 1  # cached
    clock.t = 301
    info.get("study-buddy-qwen")
    assert len(fetches) == 2


def test_ollama_lookup_failure_is_cached_and_harmless():
    calls, clock = [], Clock()

    def boom():
        calls.append(1)
        raise ConnectionError("refused")

    info = OllamaModelInfo("http://x/v1", fetch=boom, clock=clock)
    assert info.version("study-buddy-qwen", "study-buddy-qwen") == "study-buddy-qwen"
    assert info.models() is None and len(calls) == 1  # not retried within FAILED_TTL_SEC
    clock.t = 31
    info.models()
    assert len(calls) == 2


def test_llm_client_stores_resolved_version(settings, session_factory, db, tmp_path):
    (tmp_path / "p.yaml").write_text("id: p\nversion: v1\nsystem: s\nuser: u\n", encoding="utf-8")
    resolver = ModelVersionResolver(OllamaModelInfo("http://x/v1", fetch=lambda: TAGS))
    client = LLMClient(settings, session_factory, PromptRegistry(tmp_path), load_pricing(),
                       providers={"ollama": FakeProvider("ollama", [ok("a", model_version="study-buddy-qwen")]),
                                  "groq": FakeProvider("groq", [ok("b", model_version="openai/gpt-oss-120b")])},
                       sleep=lambda _s: None, rate_limiters={}, version_resolver=resolver)
    r = client.complete(task="t", prompt_id="p", provider="ollama", model="study-buddy-qwen")
    assert r.model_version == f"study-buddy-qwen@sha256:{DIGEST}"
    client.complete(task="t", prompt_id="p", provider="groq")
    rows = {row.provider: row.model_version for row in db.query(LLMCall).all()}
    assert rows == {"ollama": f"study-buddy-qwen@sha256:{DIGEST}", "groq": "openai/gpt-oss-120b"}


def test_resolver_error_never_fails_the_request(settings, session_factory, tmp_path):
    (tmp_path / "p.yaml").write_text("id: p\nversion: v1\nsystem: s\nuser: u\n", encoding="utf-8")

    def broken(*_a):
        raise RuntimeError("boom")

    client = LLMClient(settings, session_factory, PromptRegistry(tmp_path), load_pricing(),
                       providers={"ollama": FakeProvider("ollama", [ok("a", model_version="m")])},
                       sleep=lambda _s: None, rate_limiters={}, version_resolver=broken)
    assert client.complete(task="t", prompt_id="p", provider="ollama", model="m").text == "a"


def test_reasoning_effort_only_for_reasoning_models():
    assert supports_reasoning_effort("groq", "openai/gpt-oss-120b")
    assert supports_reasoning_effort("openai", "gpt-5-mini")
    assert not supports_reasoning_effort("groq", "qwen/qwen3.8-27b")
    assert not supports_reasoning_effort("ollama", "openai/gpt-oss-120b")


def test_embedding_version_includes_revision(settings, session_factory, db, fake_embedder):
    class RevEmbedder(type(fake_embedder)):
        revision = "5c38ec7c"

    assert model_version_of(fake_embedder) == "fake-embedder"
    client = EmbeddingClient(settings, session_factory, load_pricing(), embedder=RevEmbedder())
    client.embed(["hello"], task="t")
    assert db.query(LLMCall).one().model_version == "fake-embedder@5c38ec7c"


def test_reopened_chat_shows_model_without_digest():
    from types import SimpleNamespace

    from app.services.chat import _display_model

    r = SimpleNamespace(generator="finetuned", model=f"study-buddy-qwen@sha256:{DIGEST}")
    assert _display_model(r) == "finetuned:study-buddy-qwen"
    assert _display_model(SimpleNamespace(generator="cloud", model=None)) == "cloud"
    assert _display_model(SimpleNamespace(generator="cloud", model="openai/gpt-oss-120b")) == "cloud:openai/gpt-oss-120b"


# ---------------------------------------------------------------------------- registry


def _training(tmp_path):
    (tmp_path / "training.json").write_text(json.dumps({
        "started_at": "2026-11-08T09:00:00Z", "gpu": "Tesla T4",
        "config": {"base_model": "unsloth/Qwen3-1.7B", "base_model_revision": "6262b50d", "load_in_4bit": True,
                   "lora": {"r": 16}},
        "dataset": {"name": "allenai/sciq", "revision": "2c94ad3e", "train_examples": 3000},
        "exports": {"gguf_file": "study-buddy-qwen-q4_k_m.gguf", "gguf_bytes": 1107404864},
    }), encoding="utf-8")


def test_finetune_details_from_results_file(settings, tmp_path):
    s = settings.model_copy(update={"finetune_results_dir": str(tmp_path), "finetuned_hub_repo": "me/repo"})
    assert finetune_details(s)["base_model"] is None  # no file -> nulls, never invented
    _training(tmp_path)
    d = finetune_details(s)
    assert (d["base_model_revision"], d["dataset_revision"], d["gguf_bytes"], d["hub_repo"], d["method"]) == (
        "6262b50d", "2c94ad3e", 1107404864, "me/repo", "QLoRA")


@pytest.fixture
def registry_app(app, settings, generator_registry, tmp_path):
    _training(tmp_path)
    s = settings.model_copy(update={"finetune_results_dir": str(tmp_path)})
    service = ModelRegistryService(s, generator_registry, PromptRegistry(),
                                   OllamaModelInfo("http://x/v1", fetch=lambda: TAGS))
    app.dependency_overrides[get_model_registry_dep] = lambda: service
    return app


def test_llmops_models_endpoint(registry_app, client, auth_headers, db):
    db.add(LLMCall(task="rag_answer", provider="groq", model="openai/gpt-oss-120b", model_version="openai/gpt-oss-120b",
                   status="ok", attempt=1))
    db.commit()
    body = client.get("/api/llmops/models", headers=auth_headers).json()
    gens = {g["name"]: g for g in body["generators"]}
    assert gens["cloud"]["version"] == "openai/gpt-oss-120b"
    assert gens["finetuned"]["digest"] == DIGEST and gens["finetuned"]["available"] is True
    assert gens["finetuned"]["details"]["quantization_level"] == "Q4_K_M"
    assert gens["finetuned"]["details"]["finetune"]["dataset"] == "allenai/sciq"
    assert gens["base"]["available"] is False  # qwen3:1.7b is not in the fake tag list
    kinds = {o["kind"]: o for o in body["others"]}
    assert kinds["judge"]["model"] == "qwen/qwen3.8-27b"
    assert kinds["asr"]["note"]  # Groq ASR reports no model string
    assert {"id": "eval_faithfulness", "version": "v1", "tag": "eval_faithfulness@v1"} in body["prompts"]


def test_models_list_is_backward_compatible(registry_app, client, auth_headers):
    body = client.get("/api/models", headers=auth_headers).json()
    assert [g["name"] for g in body] == ["cloud", "finetuned", "base"]
    assert {"name", "provider", "model", "description", "version", "last_used_at", "details"} <= set(body[0])
    assert body[1]["details"]["finetune"]["gguf_bytes"] == 1107404864 and body[0]["details"] is None
