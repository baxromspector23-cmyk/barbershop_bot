"""Independent review, round 3. READ-ONLY: do not edit, rename, move or delete this file.
Every test asserts the CORRECT behaviour. A failure = a real defect.

Run on PostgreSQL (needed for Z2 and Z3; they are skipped on SQLite and the report must show 0 skipped on the PostgreSQL run):
    REQUIRE_PG=1 TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:port/barbershop_test python -m pytest tests/test_review_round3.py -v
Z1b builds a fresh virtualenv from requirements.lock (needs network, ~1 min). Run it with the same Python version as the Dockerfile (3.12).
Set SKIP_FRESH_VENV=1 only if you have no network, and then report Z1b as NOT RUN.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from packaging.version import Version
from sqlalchemy import text

from app.config import settings
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueService

ROOT = Path(__file__).resolve().parent.parent
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
pg_only = pytest.mark.skipif("postgresql" not in TEST_DB_URL, reason="needs real PostgreSQL (TEST_DATABASE_URL)")


def _pin(lock_text: str, name: str) -> Version | None:
    m = re.search(rf"^{re.escape(name)}==([0-9][^\s;#]*)", lock_text, re.I | re.M)
    return Version(m.group(1)) if m else None


def _lower_bound(req_text: str, name: str) -> Version | None:
    m = re.search(rf"^{re.escape(name)}(?:\[[^\]]*\])?\s*>=\s*([0-9][^\s,;#]*)", req_text, re.I | re.M)
    return Version(m.group(1)) if m else None


def test_Z1_dependency_bounds_must_match_what_the_code_imports():
    """app/config.py imports `NoDecode`, which exists only in pydantic-settings >= 2.7.0. requirements.txt allowed >=2.2.0 and
    requirements.lock (the file the Dockerfile installs) pinned 2.3.4, so the container died with
    `ImportError: cannot import name 'NoDecode' from 'pydantic_settings'`."""
    if "NoDecode" not in (ROOT / "app" / "config.py").read_text(encoding="utf-8"):
        pytest.skip("config.py no longer uses NoDecode")
    need = Version("2.7.0")
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    lb = _lower_bound(req, "pydantic-settings")
    pin = _pin(lock, "pydantic-settings")
    assert lb is not None and lb >= need, f"requirements.txt lower bound for pydantic-settings is {lb}, needs >= {need}"
    assert pin is not None and pin >= need, f"requirements.lock pins pydantic-settings {pin}, needs >= {need}"


@pytest.mark.skipif(os.environ.get("SKIP_FRESH_VENV") == "1", reason="SKIP_FRESH_VENV=1 (no network)")
def test_Z1b_requirements_lock_must_install_and_import_in_a_fresh_virtualenv():
    """This is what the Dockerfile does: pip install -r requirements.lock, then start the app."""
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, "-m", "venv", d], check=True, timeout=120)
        py = str(Path(d) / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python"))
        inst = subprocess.run([py, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.lock")],
                              capture_output=True, text=True, timeout=900)
        assert inst.returncode == 0, f"pip install -r requirements.lock failed:\n{inst.stderr[-1500:]}"
        code = f"import sys; sys.path.insert(0, r'{ROOT}'); import app.main; print('IMPORT_OK')"
        run = subprocess.run([py, "-I", "-c", code], capture_output=True, text=True, timeout=120, cwd=d)
        assert "IMPORT_OK" in run.stdout, f"import app.main failed in a fresh venv built from requirements.lock:\n{run.stderr[-1500:]}"


@pg_only
@pytest.mark.asyncio
async def test_Z2_owner_must_be_alerted_when_recording_a_payment_fails_with_an_aborted_transaction(
    session_factory, sample_barber, sample_clients, mock_notifier, monkeypatch
):
    """A real database error aborts the PostgreSQL transaction. The critical-failure alert then asks the same session for the owner's
    language, which raises 'current transaction is aborted', so the alert is never sent: money taken, nothing recorded, owner not told."""
    async with session_factory() as s:
        o = await QueueService(s, notifier=mock_notifier).join_queue(
            sample_barber.id, sample_barber.services[0].id, sample_clients[0], pay_now=True)
        await s.commit()
        order_id, price = o.id, o.price

    async def boom(self, **kwargs):
        await self.session.execute(text("select 1/0"))  # genuine DB error: transaction is now aborted

    monkeypatch.setattr(PaymentService, "_execute_successful_payment", boom)
    monkeypatch.setattr(settings, "OWNER_TELEGRAM_IDS", [777001])
    async with session_factory() as s:
        try:
            await PaymentService(s, notifier=mock_notifier).handle_successful_payment("CLICK", "tx-lost", price, order_id)
        except Exception:
            pass
    alerts = [e for e in mock_notifier.sent_events if e["telegram_id"] == 777001]
    assert alerts, "payment recording failed and the owner was NOT told"
    joined = " ".join(str(e) for e in alerts)
    assert "tx-lost" in joined and str(order_id) in joined, "the alert must contain the charge id and the order id"


@pg_only
@pytest.mark.asyncio
async def test_Z3_alembic_check_must_be_clean_on_postgresql(test_engine, monkeypatch):
    """On PostgreSQL (schema built by `alembic upgrade head`, as conftest does), `alembic check` still reported:
    'Detected removed unique constraint barbers_user_id_key on barbers' (the model declares a unique index instead)."""
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    monkeypatch.delenv("DATABASE_DIRECT_URL", raising=False)

    def run():
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
        command.check(cfg)  # raises when models and migrations differ

    await asyncio.to_thread(run)
