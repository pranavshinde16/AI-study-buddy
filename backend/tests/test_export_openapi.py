"""scripts/export_openapi.py writes the real FastAPI schema (no server, no network)."""

import json

from scripts.export_openapi import main, operations


def test_export_writes_schema_with_every_router(tmp_path):
    out = tmp_path / "openapi.json"
    main(["--out", str(out)])
    schema = json.loads(out.read_text(encoding="utf-8"))
    ops = {(m, p) for m, p, _, _ in operations(schema)}
    for expected in [("POST", "/api/auth/login"), ("POST", "/api/lectures/upload"),
                     ("POST", "/api/lectures/{lecture_id}/ask"), ("POST", "/api/quizzes/{quiz_id}/submit"),
                     ("POST", "/api/flashcards/{card_id}/review"), ("GET", "/api/llmops/eval/compare"),
                     ("GET", "/api/models"), ("GET", "/api/health")]:
        assert expected in ops


def test_operations_lists_status_codes():
    schema = {"paths": {"/x": {"get": {"summary": "S", "responses": {"404": {}, "200": {}}}, "parameters": []}}}
    assert operations(schema) == [("GET", "/x", "S", ["200", "404"])]
