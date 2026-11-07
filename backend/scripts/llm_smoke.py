"""Manual check: one real call through the LLM client to your configured provider (Groq by default).

    cd backend
    python -m scripts.llm_smoke            # uses LLM_PROVIDER / LLM_MODEL from .env
    python -m scripts.llm_smoke --provider ollama --model qwen3:1.7b

It prints the result and the llm_calls row id. Needs the database running and migrated.
This uses your free Groq quota (one small request); it never calls OpenAI unless you pass --provider openai.
"""

import argparse
import sys

from pydantic import BaseModel

from app.core.errors import AppError
from app.core.logging import configure_logging
from app.services.llm.client import get_llm_client


class SmokeOut(BaseModel):
    echo: str
    ok: bool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default=None, help="groq | openai | ollama (default: LLM_PROVIDER)")
    parser.add_argument("--model", default=None, help="override the model (default: LLM_MODEL)")
    args = parser.parse_args()

    configure_logging("WARNING", json_logs=False)
    client = get_llm_client()
    try:
        result = client.complete(
            task="smoke_test",
            prompt_id="smoke_test",
            variables={"word": "pineapple"},
            schema=SmokeOut,
            provider=args.provider,
            model=args.model,
        )
    except AppError as exc:
        print(f"FAILED [{exc.code}] {exc.message}")
        return 1

    print(f"provider      : {result.provider}")
    print(f"model         : {result.model}  (reported: {result.model_version})")
    print(f"prompt        : {result.prompt_version}")
    print(f"parsed output : {result.data}")
    print(f"tokens        : in={result.input_tokens} out={result.output_tokens}")
    print(f"latency_ms    : {result.latency_ms:.0f}")
    print(f"cost_usd      : {result.cost_usd}")
    print(f"llm_calls ids : {[str(i) for i in result.call_ids]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
