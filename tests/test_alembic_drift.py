from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parent.parent
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
pg_only = pytest.mark.skipif("postgresql" not in TEST_DB_URL, reason="needs real PostgreSQL (TEST_DATABASE_URL)")


def test_alembic_upgrade_to_head_and_schema_drift_sqlite(monkeypatch):
    """Verify Alembic migrations run cleanly and command.check detects 0 drift on SQLite."""
    with tempfile.TemporaryDirectory() as d:
        db_url = f"sqlite:///{d}/drift.db"
        monkeypatch.setenv("DATABASE_URL", db_url)
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "head")
        command.check(cfg)


@pg_only
def test_alembic_upgrade_to_head_and_schema_drift_postgres(monkeypatch):
    """Verify Alembic migrations run cleanly and command.check detects 0 drift on PostgreSQL."""
    sync_pg_url = TEST_DB_URL.replace("postgresql+asyncpg://", "postgresql://")
    monkeypatch.setenv("DATABASE_URL", sync_pg_url)
    monkeypatch.delenv("DATABASE_DIRECT_URL", raising=False)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", sync_pg_url)
    command.upgrade(cfg, "head")
    command.check(cfg)
