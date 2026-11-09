"""Export the backend's OpenAPI schema to docs/openapi.json (Phase 13).

The schema is built by FastAPI from the routers and Pydantic models, so it is always the real
contract. docs/api.md explains it in prose; this file is the machine-readable copy (import it into
Postman or Insomnia, or diff it between versions). No server and no database are needed.

    cd backend
    python -m scripts.export_openapi                       # writes ../docs/openapi.json
    python -m scripts.export_openapi --out openapi.json
"""

import argparse
import json
from pathlib import Path
from typing import Any

from app.core.config import REPO_ROOT

DEFAULT_OUT = REPO_ROOT / "docs" / "openapi.json"
METHODS = ("get", "post", "put", "patch", "delete")


def build_schema() -> dict[str, Any]:
    from app.main import app

    return app.openapi()


def operations(schema: dict[str, Any]) -> list[tuple[str, str, str, list[str]]]:
    """(METHOD, path, summary, sorted status codes) for every operation, in schema order."""
    rows = []
    for path, item in schema.get("paths", {}).items():
        for method in METHODS:
            op = item.get(method)
            if op is not None:
                rows.append((method.upper(), path, op.get("summary", ""), sorted(op.get("responses", {}))))
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    schema = build_schema()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} ({len(operations(schema))} operations, version {schema['info']['version']})")


if __name__ == "__main__":
    main()
