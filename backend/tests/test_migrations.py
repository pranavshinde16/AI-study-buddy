"""The Alembic migrations create exactly the tables the models define (runs on a temp SQLite file)."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
from app.db.base import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_upgrade_creates_all_model_tables_and_downgrade_removes_them(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "head")
    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)

    llm_cols = {c["name"] for c in inspect(engine).get_columns("llm_calls")}
    assert {
        "ts", "user_id", "lecture_id", "task", "provider", "model", "model_version", "prompt_id",
        "prompt_version", "input_tokens", "output_tokens", "latency_ms", "cost_usd", "status",
        "error_type", "error_message", "request_hash",
    } <= llm_cols  # every field listed in IMPLEMENTATION_PLAN §7.1

    def cols(table: str) -> set[str]:
        return {c["name"] for c in inspect(engine).get_columns(table)}

    # Phase 6 migration
    assert "rubric_json" in cols("quiz_questions") and "score" in cols("attempt_answers")
    assert {"kind", "source_start"} <= cols("flashcards")

    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) - {"alembic_version"} == set()
    engine.dispose()
