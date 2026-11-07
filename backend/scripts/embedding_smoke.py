"""Manual check: load the real local embedding model once and compare a few sentences.

    cd backend
    python -m scripts.embedding_smoke

The first run downloads BAAI/bge-small-en-v1.5 (~130 MB) into your Hugging Face cache
(Windows: %USERPROFILE%\\.cache\\huggingface, macOS/Linux: ~/.cache/huggingface); later runs
load it from disk. It prints the load time, the similarity of each sentence to the reference,
and whether each would pass the short-answer fallback threshold (SHORT_ANSWER_SIM_THRESHOLD).
Each embed() call writes an `llm_calls` row (task=embedding_smoke, provider=local, cost 0),
so the database must be running and migrated. Free: nothing is sent to any API.
"""

import sys
import time

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.services.embeddings import cosine, get_embedder, get_embedding_client

REFERENCE = "Mitochondria produce most of the cell's energy in the form of ATP."
ANSWERS = [
    "The mitochondria make ATP, which is the cell's main energy source.",
    "Energy in cells mostly comes from mitochondria.",
    "The nucleus stores the cell's genetic information.",
    "Photosynthesis happens in the leaves of plants.",
]


def main() -> int:
    configure_logging("WARNING", json_logs=False)
    settings = get_settings()
    client = get_embedding_client()
    embedder = get_embedder()
    print(f"model     : {settings.embedding_model} on {settings.embedding_device}")
    print(f"loaded    : {embedder.loaded} (the model loads on the first call)")

    try:
        start = time.perf_counter()
        client.embed(["warm-up"], task="embedding_smoke")
        first = time.perf_counter() - start
        start = time.perf_counter()
        vectors = client.embed([REFERENCE, *ANSWERS], task="embedding_smoke")
        second = time.perf_counter() - start
    except AppError as exc:
        print(f"FAILED [{exc.code}] {exc.message}")
        return 1

    print(f"first call (load + embed 1 text): {first:.2f} s  (llm_calls latency excludes the load)")
    print(f"second call (embed {len(vectors)} texts)  : {second:.3f} s")
    print(f"dimensions: {len(vectors[0])}")
    print(f"\nreference : {REFERENCE}")
    threshold = settings.short_answer_sim_threshold
    for text, vec in zip(ANSWERS, vectors[1:]):
        sim = cosine(vectors[0], vec)
        verdict = "correct" if sim >= threshold else "wrong"
        print(f"  {sim:.3f}  {verdict:<7}  {text}")
    print(f"(threshold SHORT_ANSWER_SIM_THRESHOLD = {threshold})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
