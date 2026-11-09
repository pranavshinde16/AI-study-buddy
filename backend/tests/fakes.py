"""Fake LLM provider for tests: plays back a scripted list of results or errors. No network."""

from app.services.llm.providers import ChatResult, ProviderError


class FakeProvider:
    def __init__(self, name: str, script: list[ChatResult | ProviderError] | None = None, responder=None) -> None:
        self.name = name
        self.script = list(script or [])
        self.responder = responder
        self.calls: list[dict] = []

    def chat(self, *, model, messages, json_mode, max_output_tokens, temperature, reasoning_effort=None) -> ChatResult:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "json_mode": json_mode,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "reasoning_effort": reasoning_effort,
            }
        )
        if self.responder is not None:  # a function of the messages -> reply (see FakeLectureLLM)
            item = self.responder(messages)
            if isinstance(item, ProviderError):
                raise item
            return item
        if not self.script:
            raise AssertionError(f"FakeProvider '{self.name}' called more times than scripted")
        item = self.script.pop(0)
        if isinstance(item, ProviderError):
            raise item
        return item


def ok(text: str, *, model_version: str = "fake-model-2026", inp: int = 100, out: int = 20) -> ChatResult:
    return ChatResult(text=text, model_version=model_version, input_tokens=inp, output_tokens=out)


def rate_limited(retry_after: float | None = None) -> ProviderError:
    return ProviderError("rate_limited", "429 Too Many Requests", error_type="RateLimitError", retry_after=retry_after)


# ---------------------------------------------------------------------------- speech recognition

from pathlib import Path  # noqa: E402

from app.services.asr.providers import ASRResult, ASRSegment  # noqa: E402


class FakeASRProvider:
    """Scripted ASR provider. With no script it returns two segments per chunk:
    0.0–1.0 "part <n> hello" and 1.0–1.9 "part <n> world". `on_call(path)` runs before each reply."""

    def __init__(self, name: str = "groq", script: list[ASRResult | ProviderError] | None = None, on_call=None) -> None:
        self.name = name
        self.script = list(script) if script is not None else None
        self.calls: list[dict] = []
        self.on_call = on_call

    def transcribe(self, path: Path, *, model: str, language: str | None) -> ASRResult:
        self.calls.append({"path": Path(path), "model": model, "language": language})
        if self.on_call is not None:
            self.on_call(Path(path))
        if self.script is None:
            n = len(self.calls)
            return ASRResult(
                segments=[ASRSegment(0.0, 1.0, f"part {n} hello"), ASRSegment(1.0, 1.9, f"part {n} world")],
                language="en",
            )
        if not self.script:
            raise AssertionError(f"FakeASRProvider '{self.name}' called more times than scripted")
        item = self.script.pop(0)
        if isinstance(item, ProviderError):
            raise item
        return item


def asr_ok(*segments: tuple[float, float, str], language: str = "en", duration: float | None = None) -> ASRResult:
    return ASRResult(segments=[ASRSegment(s, e, t) for s, e, t in segments], language=language, duration_sec=duration)


# ---------------------------------------------------------------------------- lecture LLM (Phase 5)

import json  # noqa: E402
import re  # noqa: E402

_RANGE = re.compile(r"segments \[(\d+)\] to \[(\d+)\]")


class FakeLectureLLM:
    """Responder for FakeProvider: answers the topics / notes / summary prompts with valid JSON.

    It recognises the prompt from the JSON Schema the client appends to the system message.
    `topics`: splits the window's segment range into two topics (deliberately overlapping and
    one id out of range, to exercise the app's clamping) plus one definition on the first id.
    Set `fail[task] = ProviderError(...)` to make a task fail, or `invalid[task] = True` to
    return JSON that does not match the schema.
    """

    def __init__(self) -> None:
        self.tasks: list[str] = []
        self.user_messages: list[str] = []
        self.fail: dict[str, ProviderError] = {}
        self.invalid: dict[str, bool] = {}
        # Phase 6: defects applied to the items of the NEXT quiz call, one per item, in order
        # (see _quiz_item); "always_invalid" makes every quiz item invalid on every call.
        self.quiz_defects: list[str] = []
        self.quiz_always_invalid = False
        self.grading_skip: set[str] = set()  # item ids the fake grader leaves out
        self._quiz_calls = 0
        # Phase 7: the RAG answer cites these ids ("C9" is normally not a real one, to test
        # that invalid citations are dropped); set rag_answerable=False to make it refuse.
        self.rag_answerable = True
        self.rag_citations: list[str] = ["C1", "C9"]
        # Phase 11 judge replies
        self.judge_supported: list[bool] = [True, True]
        self.judge_score: float = 1.0

    @staticmethod
    def task_of(system: str) -> str:
        if '"citations"' in system:
            return "rag_answer"
        if '"standalone_question"' in system:
            return "rag_rewrite"
        if '"slot"' in system:
            return "quiz"
        if '"grades"' in system:
            return "grading"
        if '"front"' in system:
            return "flashcards"
        if '"start_segment"' in system:
            return "topics"
        if '"notes_md"' in system:
            return "notes"
        if '"key_takeaways"' in system:
            return "summary"
        if '"claims"' in system:
            return "eval_faithfulness"
        if '"reason"' in system and '"score"' in system:
            return "eval_correctness"
        return "other"

    def __call__(self, messages):
        system, user = messages[0]["content"], messages[1]["content"]
        task = self.task_of(system)
        self.tasks.append(task)
        self.user_messages.append(user)
        if task in self.fail:
            return self.fail[task]
        if self.invalid.get(task):
            return ok('{"unexpected": true}')
        if task == "topics":
            lo, hi = (int(x) for x in _RANGE.search(user).groups())
            mid = (lo + hi) // 2
            body = {
                "topics": [
                    {"title": f"Topic {lo}", "start_segment": lo, "end_segment": mid + 1, "key_points": [f"point {lo}"]},
                    {"title": f"Topic {mid}", "start_segment": mid, "end_segment": hi + 50, "key_points": [f"point {mid}"]},
                ],
                "definitions": [
                    {"term": f"Term {lo}", "definition": "as explained (not stated in lecture)", "segment_id": lo},
                    {"term": "Ghost", "definition": "id outside the window", "segment_id": hi + 999},
                ],
            }
        elif task == "notes":
            topic = re.search(r"Topic: (.*)", user).group(1)
            body = {"notes_md": f"- **{topic}** notes from the transcript"}
        elif task == "summary":
            body = {"summary": "The lecture covers the topics.", "key_takeaways": ["Takeaway one", "Takeaway two"],
                    "revision_notes_md": "- revise **this**"}
        elif task == "quiz":
            body = self._quiz(user)
        elif task == "grading":
            body = self._grades(user)
        elif task == "flashcards":
            body = self._cards(user)
        elif task == "rag_answer":
            inline = " ".join(f"[{c}]" for c in self.rag_citations)
            body = {"answerable": self.rag_answerable,
                    "answer": f"From the lecture: cells turn food into energy {inline}." if self.rag_answerable
                    else "The excerpts don't cover this.",
                    "citations": list(self.rag_citations) if self.rag_answerable else []}
        elif task == "rag_rewrite":
            latest = re.search(r"Latest message: (.*)", user).group(1).strip()
            body = {"standalone_question": f"{latest} (about how cells make energy)"}
        elif task == "eval_faithfulness":  # Phase 11 judge: claims[i] supported = judge_supported[i]
            body = {"claims": [{"claim": f"claim {i}", "supported": s, "evidence": ["C1"] if s else []}
                               for i, s in enumerate(self.judge_supported)]}
        elif task == "eval_correctness":
            body = {"score": self.judge_score, "reason": "fake judge"}
        else:
            body = {}
        return ok(json.dumps(body), model_version="openai/gpt-oss-120b", inp=300, out=120)

    # ------------------------------------------------------------------ Phase 6 tasks

    _SLOT = re.compile(r"- slot (\d+): (\w+), (\w+)")

    def _quiz(self, user: str) -> dict:
        self._quiz_calls += 1
        lo, hi = (int(x) for x in _RANGE.search(user).groups())
        defects, self.quiz_defects = list(self.quiz_defects), []
        items = []
        for i, (slot, qtype, _diff) in enumerate(self._SLOT.findall(user)):
            seg = lo + (int(slot) - 1) % (hi - lo + 1)
            item = self._quiz_item(int(slot), qtype, seg)
            defect = "always_invalid" if self.quiz_always_invalid else (defects[i] if i < len(defects) else None)
            if defect == "drop":
                continue
            items.append(self._apply_defect(item, defect, hi) if defect else item)
        return {"questions": items}

    def _quiz_item(self, slot: int, qtype: str, seg: int) -> dict:
        q = f"Question {self._quiz_calls}.{slot}: what does segment {seg} explain?"
        base = {"slot": slot, "type": qtype, "question": q, "explanation": f"Segment {seg} says so.",
                "segment_id": seg, "options": [], "key_points": []}
        if qtype == "mcq":
            opts = [f"Choice {k} of {self._quiz_calls}.{slot}" for k in range(1, 5)]
            return {**base, "options": opts, "answer": opts[1]}
        if qtype == "true_false":
            return {**base, "answer": True}
        return {**base, "answer": "the reference answer about energy", "key_points": ["energy"]}

    @staticmethod
    def _apply_defect(item: dict, defect: str, hi: int) -> dict:
        item = dict(item)
        if defect in ("duplicate_options", "always_invalid") and item["type"] == "mcq":
            item["options"] = [item["options"][0]] * 2 + item["options"][2:]
        elif defect == "answer_not_in_options":
            item["answer"] = "Something else entirely" if item["type"] != "true_false" else "maybe"
        elif defect == "three_options":
            item["options"] = item["options"][:3]
        elif defect in ("segment_out_of_range", "always_invalid"):
            item["segment_id"] = hi + 500
        elif defect == "wrong_type":
            item["type"] = "true_false" if item["type"] != "true_false" else "mcq"
        elif defect == "unknown_slot":
            item["slot"] = 99
        return item

    def _grades(self, user: str) -> dict:
        items = json.loads(user.split("Items to grade (JSON):", 1)[1])
        grades = []
        for it in items:
            if it["id"] in self.grading_skip:
                continue
            good = "energy" in it["student_answer"].lower()
            grades.append({"id": it["id"], "score": 1.0 if good else 0.0, "correct": good,
                           "feedback": "Covers the key point." if good else "Misses the key point."})
        return {"grades": grades}

    @staticmethod
    def _cards(user: str) -> dict:
        lo, hi = (int(x) for x in _RANGE.search(user).groups())
        return {
            "cards": [
                {"front": f"How does part {lo} work?", "back": "As the lecturer explains.", "segment_id": lo},
                {"front": f"how does PART {lo} work", "back": "Duplicate with other casing.", "segment_id": lo},
                {"front": f"What is Term {lo}?", "back": "Duplicates a definition card.", "segment_id": lo},
                {"front": "Where is this from?", "back": "Segment outside the batch.", "segment_id": hi + 100},
                {"front": f"Why does segment {hi} matter?", "back": "Because it closes the part.", "segment_id": hi},
            ]
        }


# ---------------------------------------------------------------------------- embeddings (Phase 6)

import hashlib  # noqa: E402
import math  # noqa: E402


class FakeEmbedder:
    """Deterministic bag-of-words vectors (64 dims, L2-normalised). No model, no download."""

    model_name = "fake-embedder"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail: Exception | None = None

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail is not None:
            raise self.fail
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out
