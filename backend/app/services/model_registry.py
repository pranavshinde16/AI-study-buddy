"""Model registry for LLMOps (Phase 11): which model, which exact version, from where.

    generators  cloud / finetuned / base (+ configured): provider, model, the last model string
                the provider returned (llm_calls.model_version) and, for Ollama, the live digest,
                size and quantisation from `GET /api/tags`.
    finetuned   + base model and revision, dataset and revision, GGUF file and size, trained on,
                all read from finetune/results/training.json (FINETUNE_RESULTS_DIR), and the Hub
                repo from FINETUNED_HUB_REPO. Nothing is hardcoded; a missing file gives nulls.
    asr         provider/model + last reported version (Groq's transcription response has no
                model field, so it is null there and the note says so).
    embedding   model + the Hugging Face commit of the local copy.
    judge       the eval-harness judge (EVAL_JUDGE_MODEL) + last reported version.
    prompts     every prompt id with its current version.
"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.llmops import LLMCall
from app.services.asr.providers import model_for
from app.services.embeddings import cached_revision
from app.services.llm.generators import GeneratorRegistry
from app.services.llm.model_info import OllamaModelInfo
from app.services.llm.prompts import PromptRegistry

TRAINING_FILE = "training.json"


def read_training(results_dir: Path) -> dict[str, Any] | None:
    path = results_dir / TRAINING_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def finetune_details(settings: Settings) -> dict[str, Any]:
    """Provenance of the fine-tuned model, from results/training.json + FINETUNED_HUB_REPO."""
    t = read_training(settings.finetune_results_path)
    cfg = (t or {}).get("config") or {}
    ds = (t or {}).get("dataset") or {}
    ex = (t or {}).get("exports") or {}
    return {
        "source_file": str(settings.finetune_results_path / TRAINING_FILE) if t else None,
        "base_model": cfg.get("base_model"),
        "base_model_revision": cfg.get("base_model_revision"),
        "loaded_from": cfg.get("loaded_from"),
        "dataset": ds.get("name"),
        "dataset_revision": ds.get("revision"),
        "train_examples": ds.get("train_examples"),
        "validation_examples": ds.get("validation_examples"),
        "method": "QLoRA" if cfg.get("load_in_4bit") and cfg.get("lora") else None,
        "lora": cfg.get("lora"),
        "gguf_file": ex.get("gguf_file"),
        "gguf_bytes": ex.get("gguf_bytes"),
        "trained_at": (t or {}).get("started_at"),
        "gpu": (t or {}).get("gpu"),
        "hub_repo": settings.finetuned_hub_repo or None,
    }


class ModelRegistryService:
    def __init__(self, settings: Settings, generators: GeneratorRegistry, prompts: PromptRegistry,
                 ollama: OllamaModelInfo | None) -> None:
        self.settings = settings
        self.generators = generators
        self.prompts = prompts
        self.ollama = ollama

    # ------------------------------------------------------------------ shared lookups

    @staticmethod
    def last_seen(db: Session, provider: str, model: str, task: str | None = None) -> dict[str, Any]:
        q = (select(LLMCall.model_version, LLMCall.ts).where(LLMCall.provider == provider, LLMCall.model == model,
                                                             LLMCall.status == "ok"))
        if task:
            q = q.where(LLMCall.task == task)
        row = db.execute(q.order_by(LLMCall.ts.desc()).limit(1)).first()
        return {"version": row[0] if row else None, "last_used_at": row[1] if row else None}

    def generator_versions(self, db: Session) -> dict[str, dict[str, Any]]:
        """Cheap (DB only, no network): used by GET /models for the Ask page."""
        out = {}
        for g in self.generators.all():
            seen = self.last_seen(db, g.provider, g.model)
            details = {"finetune": finetune_details(self.settings)} if g.name == "finetuned" else None
            out[g.name] = {**seen, "details": details}
        return out

    # ------------------------------------------------------------------ full registry

    def registry(self, db: Session) -> dict[str, Any]:
        s = self.settings
        ollama_models = self.ollama.models() if self.ollama is not None else None
        generators = []
        for g in self.generators.all():
            seen = self.last_seen(db, g.provider, g.model)
            entry: dict[str, Any] = {"kind": "generator", "name": g.name, "provider": g.provider, "model": g.model,
                                     "description": g.description, **seen, "digest": None, "size_bytes": None,
                                     "available": None, "details": {}}
            if g.provider == "ollama":
                m = self.ollama.get(g.model) if self.ollama is not None else None
                entry["available"] = None if ollama_models is None else m is not None
                if m is not None:
                    entry["digest"] = m.digest
                    entry["size_bytes"] = m.size_bytes
                    entry["details"] = {"modified_at": m.modified_at, **{k: m.details.get(k) for k in
                                        ("family", "parameter_size", "quantization_level", "format")}}
            if g.name == "finetuned":
                entry["details"]["finetune"] = finetune_details(s)
            generators.append(entry)

        asr_model = model_for(s.asr_provider, s)
        asr_seen = self.last_seen(db, s.asr_provider, asr_model, task="asr")
        emb_rev = cached_revision(s.embedding_model)
        judge_seen = self.last_seen(db, s.eval_judge_provider, s.eval_judge_model)
        grader_seen = self.last_seen(db, s.llm_provider, s.judge_model, task="grading")
        return {
            "ollama_reachable": None if self.ollama is None else ollama_models is not None,
            "ollama_url": s.finetuned_base_url,
            "generators": generators,
            "others": [
                {"kind": "asr", "name": "asr", "provider": s.asr_provider, "model": asr_model, **asr_seen,
                 "note": None if asr_seen["version"] else
                 "The provider's transcription response does not report a model string."},
                {"kind": "embedding", "name": "embedding", "provider": "local", "model": s.embedding_model,
                 "version": f"{s.embedding_model}@{emb_rev}" if emb_rev else None, "revision": emb_rev,
                 "last_used_at": self.last_seen(db, "local", s.embedding_model)["last_used_at"],
                 "note": None if emb_rev else "Not downloaded yet (loaded on first use)."},
                {"kind": "judge", "name": "eval_judge", "provider": s.eval_judge_provider,
                 "model": s.eval_judge_model, **judge_seen, "note": "LLM-as-judge for the eval harness"},
                {"kind": "grader", "name": "quiz_grader", "provider": s.llm_provider, "model": s.judge_model,
                 **grader_seen, "note": "Grades short quiz answers (JUDGE_MODEL)"},
            ],
            "prompts": [{"id": pid, "version": self.prompts.get(pid).version, "tag": self.prompts.get(pid).tag}
                        for pid in self.prompts.ids()],
        }
