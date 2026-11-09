"""Grounded question answering over one lecture (IMPLEMENTATION_PLAN §5.4, Phase 7).

    1. rewrite   : chat only. With earlier turns, the follow-up is rewritten into a standalone
                   question (`rag_rewrite`, RAG_REWRITE_GENERATOR).
    2. retrieve  : embed the question WITH bge's query prefix, top-k (RAG_TOP_K) chunks of
                   this lecture from the vector store; score = 1 - cosine distance.
    3. threshold : best score < RAG_MIN_SCORE -> refuse at once, with no LLM call
                   (refusal_reason = "below_threshold").
    4. answer    : the chosen generator (cloud | finetuned | base | configured) answers from the
                   chunks labelled C1..Ck (`rag_answer`). The threshold is only a first filter: the
                   model may still return answerable=false (refusal_reason = "not_in_chunks").
    5. citations : cited ids that were not provided are dropped, also from the answer text. If no
                   valid id is left, every chunk the model was given is returned as a source.
    6. sources   : start/end come from the chunks, i.e. from the transcript segments, never from
                   the model. A refusal returns the closest chunks (cited = false) instead.
"""

import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.embeddings import EmbeddingClient
from app.services.llm.generators import GeneratorRegistry
from app.services.vectorstore import Hit, VectorStore

EXCERPT_CHARS = 300
CLOSEST_ON_REFUSAL = 3
NOT_COVERED = "This isn't covered in the lecture."

_CITE = re.compile(r"\[\s*(C\d+)\s*\]", re.IGNORECASE)


class RagAnswerOut(BaseModel):
    answerable: bool = Field(description="false if the excerpts do not answer the question")
    answer: str
    citations: list[str] = Field(default_factory=list, description='excerpt ids used, e.g. ["C1", "C3"]')


class RewriteOut(BaseModel):
    standalone_question: str = Field(min_length=1)


@dataclass
class Source:
    chunk_id: str  # label shown to the model and the user: C1..Ck
    chunk_idx: int
    start: float
    end: float
    excerpt: str
    score: float
    cited: bool


@dataclass
class RetrievedChunk:
    label: str
    chunk_idx: int
    start: float
    end: float
    score: float
    text: str


@dataclass
class RagAnswer:
    answer: str
    answerable: bool
    sources: list[Source]
    question: str
    rewritten_question: str | None
    refusal_reason: str | None
    top_score: float | None
    scores: list[float]
    generator: str
    provider: str | None
    model: str | None
    prompt_version: str | None
    retrieval_ms: float
    latency_ms: float
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    citations_dropped: list[str] = field(default_factory=list)
    citation_check: str = "ok"  # ok | none_valid | n/a
    # Every retrieved chunk (C1..Ck, full text), for the eval harness (faithfulness is judged
    # against exactly what the model saw). Not part of the API response.
    retrieved: list["RetrievedChunk"] = field(default_factory=list)

    def meta(self) -> dict[str, Any]:
        return {
            "generator": self.generator, "provider": self.provider, "model": self.model,
            "prompt_version": self.prompt_version, "rewritten_question": self.rewritten_question,
            "refusal_reason": self.refusal_reason, "top_score": self.top_score, "scores": self.scores,
            "retrieval_ms": self.retrieval_ms, "latency_ms": self.latency_ms, "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "citations_dropped": self.citations_dropped, "citation_check": self.citation_check,
        }


def mmss(sec: float) -> str:
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


def _label(i: int) -> str:
    return f"C{i + 1}"


def _source(label: str, hit: Hit, cited: bool) -> Source:
    m = hit.metadata
    text = hit.text.strip()
    excerpt = text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
    return Source(label, int(m.get("idx", -1)), float(m["start"]), float(m["end"]), excerpt, round(hit.score, 4), cited)


def refusal_text(closest: Sequence[Source]) -> str:
    if not closest:
        return NOT_COVERED
    times = ", ".join(f"{mmss(s.start)}–{mmss(s.end)}" for s in sorted(closest, key=lambda s: s.start))
    return f"{NOT_COVERED} The closest parts of the lecture are at {times}."


def check_citations(answer: str, cited: Sequence[str], labels: Sequence[str]) -> tuple[str, list[str], list[str]]:
    """Return (answer with invalid [Cn] markers removed, valid ids in order, dropped ids)."""
    valid_set = {lbl.upper() for lbl in labels}
    mentioned = [c.upper() for c in cited] + [m.upper() for m in _CITE.findall(answer)]
    valid, dropped = [], []
    for c in mentioned:
        c = c.strip("[] ")
        (valid if c in valid_set else dropped).append(c)
    valid = list(dict.fromkeys(valid))
    dropped = list(dict.fromkeys(dropped))

    def _fix(m: re.Match) -> str:
        return f"[{m.group(1).upper()}]" if m.group(1).upper() in valid_set else ""

    cleaned = re.sub(r"\s{2,}", " ", _CITE.sub(_fix, answer)).replace(" .", ".").strip()
    return cleaned, sorted(valid, key=lambda c: int(c[1:])), dropped


class RagService:
    def __init__(self, settings: Settings, embeddings: EmbeddingClient, store: VectorStore,
                 generators: GeneratorRegistry) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self.store = store
        self.generators = generators

    # ------------------------------------------------------------------ steps

    def retrieve(self, lecture_id: uuid.UUID, question: str, user_id: uuid.UUID | None = None,
                 *, task: str = "rag_query") -> list[Hit]:
        [vector] = self.embeddings.embed_queries([question], task=task, lecture_id=lecture_id, user_id=user_id)
        hits = self.store.query(lecture_id, vector, self.settings.rag_top_k)
        return sorted(hits, key=lambda h: h.score, reverse=True)

    def rewrite(self, *, title: str, message: str, history: Sequence[tuple[str, str]],
                lecture_id: uuid.UUID, user_id: uuid.UUID | None) -> tuple[str, Any]:
        gen = self.generators.get(self.settings.rag_rewrite_generator)
        lines = "\n".join(f"{'Student' if role == 'user' else 'Assistant'}: {text}" for role, text in history)
        r = gen.complete(task="rag_rewrite", prompt_id="rag_rewrite", schema=RewriteOut,
                         variables={"title": title, "history": lines, "message": message},
                         lecture_id=lecture_id, user_id=user_id)
        return r.data.standalone_question.strip(), r  # type: ignore[union-attr]

    # ------------------------------------------------------------------ full flow

    def answer(
        self,
        *,
        lecture_id: uuid.UUID,
        user_id: uuid.UUID | None,
        title: str,
        question: str,
        generator: str,
        history: Sequence[tuple[str, str]] = (),
        task_prefix: str = "",
    ) -> RagAnswer:
        """`task_prefix` (e.g. "eval_") renames the logged llm_calls tasks (eval_rag_query,
        eval_rag_answer) so evaluation traffic stays out of the live-traffic metrics."""
        t0 = time.perf_counter()
        gen = self.generators.get(generator)  # unknown name -> 422 before any work
        calls = in_tok = out_tok = 0

        rewritten = None
        query = question
        if history:
            rewritten, r = self.rewrite(title=title, message=question, history=history,
                                        lecture_id=lecture_id, user_id=user_id)
            query = rewritten
            calls, in_tok, out_tok = calls + len(r.call_ids), in_tok + r.input_tokens, out_tok + r.output_tokens

        t1 = time.perf_counter()
        hits = self.retrieve(lecture_id, query, user_id, task=f"{task_prefix}rag_query")
        retrieval_ms = round((time.perf_counter() - t1) * 1000, 1)
        scores = [round(h.score, 4) for h in hits]
        top = scores[0] if scores else None
        retrieved = [RetrievedChunk(_label(i), int(h.metadata.get("idx", -1)), float(h.metadata["start"]),
                                    float(h.metadata["end"]), round(h.score, 4), h.text.strip())
                     for i, h in enumerate(hits)]

        def done(**kw: Any) -> RagAnswer:
            return RagAnswer(question=question, rewritten_question=rewritten, top_score=top, scores=scores,
                             generator=gen.name, retrieval_ms=retrieval_ms,
                             latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                             llm_calls=calls, input_tokens=in_tok, output_tokens=out_tok, retrieved=retrieved, **kw)

        closest = [_source(_label(i), h, False) for i, h in enumerate(hits[:CLOSEST_ON_REFUSAL])]
        if top is None or top < self.settings.rag_min_score:
            return done(answer=refusal_text(closest), answerable=False, sources=closest,
                        refusal_reason="below_threshold", provider=None, model=None, prompt_version=None,
                        citation_check="n/a")

        labels = [_label(i) for i in range(len(hits))]
        context = "\n\n".join(f"[{lbl}] {h.text.strip()}" for lbl, h in zip(labels, hits))
        r = gen.complete(task=f"{task_prefix}rag_answer", prompt_id="rag_answer", schema=RagAnswerOut,
                         variables={"title": title, "question": query, "chunks": context},
                         lecture_id=lecture_id, user_id=user_id)
        calls, in_tok, out_tok = calls + len(r.call_ids), in_tok + r.input_tokens, out_tok + r.output_tokens
        out: RagAnswerOut = r.data  # type: ignore[assignment]
        info = dict(provider=r.provider, model=r.model_version or r.model, prompt_version=r.prompt_version)

        if not out.answerable:
            return done(answer=refusal_text(closest), answerable=False, sources=closest,
                        refusal_reason="not_in_chunks", citation_check="n/a", **info)

        text, valid, dropped = check_citations(out.answer.strip(), out.citations, labels)
        by_label = dict(zip(labels, hits))
        if valid:
            sources = [_source(c, by_label[c], True) for c in valid]
            check = "ok"
        else:  # no usable citation: show everything the answer was based on
            sources = [_source(lbl, h, False) for lbl, h in zip(labels, hits)]
            check = "none_valid"
        return done(answer=text or NOT_COVERED, answerable=True, sources=sources, refusal_reason=None,
                    citations_dropped=dropped, citation_check=check, **info)


@lru_cache
def get_rag_service() -> RagService:
    from app.core.config import get_settings
    from app.services.embeddings import get_embedding_client
    from app.services.llm.generators import get_generator_registry
    from app.services.vectorstore import get_vector_store

    return RagService(get_settings(), get_embedding_client(), get_vector_store(), get_generator_registry())
