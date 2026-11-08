"""Generation backends for the base-vs-fine-tuned comparison (used by evaluate.py and the notebook).

Both models get the same items, the same messages (thinking off), greedy decoding and the same
max_new_tokens:
- HFBackend      in Colab: ONE 4-bit model with the LoRA adapter; "base" = adapter disabled,
                 "finetuned" = adapter enabled. Identical weights otherwise. Latency = GPU time per
                 item (batched generation divides the batch time by the batch size; recorded as such).
- OllamaBackend  locally: the OpenAI-compatible endpoint the app uses, with the same JSON mode the
                 app sends (response_format json_object). Latency = one request per item on your CPU.

This module is named eval_runner (not evaluate) so it never shadows the `evaluate` pip package.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from typing import Any

MAX_NEW_TOKENS = 256


def load_items(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def prompt_messages(item: dict[str, Any]) -> list[dict[str, str]]:
    """The item's messages without the gold assistant answer."""
    return [m for m in item["messages"] if m["role"] != "assistant"]


class OllamaBackend:
    """Calls http://<host>/v1/chat/completions like backend/app/services/llm/providers.py does."""

    def __init__(self, base_url: str = "http://localhost:11434/v1", timeout: float = 300.0,
                 json_mode: bool = True, opener: Callable[..., Any] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.json_mode = json_mode
        self._open = opener or urllib.request.urlopen

    def generate(self, model: str, items: Iterable[dict[str, Any]], max_new_tokens: int = MAX_NEW_TOKENS,
                 progress: Callable[[int], None] | None = None) -> list[dict[str, Any]]:
        outputs = []
        for i, item in enumerate(items):
            body: dict[str, Any] = {
                "model": model,
                "messages": prompt_messages(item),
                "temperature": 0,
                "max_tokens": max_new_tokens,
                "stream": False,
            }
            if self.json_mode:
                body["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            t0 = time.perf_counter()
            try:
                with self._open(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                text = data["choices"][0]["message"].get("content") or ""
                err = None
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                text, err = "", f"{type(exc).__name__}: {exc}"
            ms = (time.perf_counter() - t0) * 1000
            outputs.append({"text": text, "latency_ms": round(ms, 1) if err is None else None, "error": err})
            if progress:
                progress(i + 1)
        return outputs


class HFBackend:
    """Wraps an Unsloth/PEFT model already loaded in the notebook (4-bit + LoRA adapter)."""

    def __init__(self, model: Any, tokenizer: Any, batch_size: int = 8) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.batch_size = batch_size

    def _run(self, items: list[dict[str, Any]], max_new_tokens: int,
             progress: Callable[[int], None] | None) -> list[dict[str, Any]]:
        import torch  # noqa: PLC0415 - only in Colab

        tok = self.tokenizer
        tok.padding_side = "left"
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        outputs: list[dict[str, Any]] = []
        for start in range(0, len(items), self.batch_size):
            batch = items[start : start + self.batch_size]
            texts = [
                tok.apply_chat_template(prompt_messages(it), tokenize=False, add_generation_prompt=True, enable_thinking=False)
                for it in batch
            ]
            enc = tok(texts, return_tensors="pt", padding=True, add_special_tokens=False).to(self.model.device)
            torch.cuda.synchronize()
            t0 = time.perf_counter()
            with torch.no_grad():
                gen = self.model.generate(
                    **enc, max_new_tokens=max_new_tokens, do_sample=False, temperature=None, top_p=None, top_k=None,
                    pad_token_id=tok.pad_token_id,
                )
            torch.cuda.synchronize()
            per_item_ms = (time.perf_counter() - t0) * 1000 / len(batch)
            new_tokens = gen[:, enc["input_ids"].shape[1] :]
            for row in new_tokens:
                outputs.append({"text": tok.decode(row, skip_special_tokens=True).strip(), "latency_ms": round(per_item_ms, 1)})
            if progress:
                progress(len(outputs))
        return outputs

    def generate(self, label: str, items: list[dict[str, Any]], max_new_tokens: int = MAX_NEW_TOKENS,
                 progress: Callable[[int], None] | None = None) -> list[dict[str, Any]]:
        """label "base" runs with the LoRA adapter disabled, "finetuned" with it enabled."""
        if label == "base":
            with self.model.disable_adapter():
                return self._run(items, max_new_tokens, progress)
        return self._run(items, max_new_tokens, progress)
