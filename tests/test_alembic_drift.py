from __future__ import annotations

import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parent.parent


def test_alembic_upgrade_to_head_and_schema_drift(monkeypatch):
    """Verify Alembic migrations run cleanly and command.check detects 0 drift."""
    with tempfile.TemporaryDirectory() as d:
        db_url = f"sqlite:///{d}/drift.db"
        monkeypatch.setenv("DATABASE_URL", db_url)
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "head")
        command.check(cfg)
