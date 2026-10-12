"""Independent review, round 4. READ-ONLY: do not edit, rename, move or delete this file.
Every test asserts the CORRECT behaviour. A failure = a real defect.

All four tests run on SQLite and on PostgreSQL (no skips expected on either).
    python -m pytest tests/test_review_round4.py -v
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.handlers import owner as owner_handlers
from app.handlers import payments as payment_handlers
from app.i18n import t
from app.models.enums import UserRole
from app.models.user import User
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueService

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _fresh_process_local_locks():
    getattr(QueueService, "_barber_locks", {}).clear()
    yield


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_Y1_the_dockerfile_build_time_import_check_must_actually_work_from_the_image_workdir():
    """The Dockerfile has `RUN python -I -c "import app.main"` with WORKDIR /app. Python's -I (isolated) mode does NOT put the
    current directory on sys.path, so this line dies with `ModuleNotFoundError: No module named 'app'` and `docker build` fails
    for every build. This test executes the Dockerfile's own RUN line(s) from the project root with a minimal environment."""
    lines = [ln.strip() for ln in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
             if ln.strip().startswith("RUN") and "import app" in ln]
    assert lines, "the Dockerfile must contain a build-time `RUN python ... -c \"import app.main\"` check"
    keep = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "HOME", "VIRTUAL_ENV")
    env = {k: v for k, v in os.environ.items() if k in keep}
    for line in lines:
        cmd = shlex.split(line[len("RUN"):].strip())
        assert cmd[0] in ("python", "python3"), f"unexpected command in Dockerfile: {line}"
        cmd[0] = sys.executable
        run = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, f"`{line}` fails inside the project directory:\n{run.stderr[-800:]}"


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", ["ru", "uz_cyrl"])
async def test_Y2_owner_barber_list_screen_must_be_fully_translated(lang, db_session, sample_barber):
    """handle_owner_back_to_barbers still builds the list with a hard-coded Uzbek-Latin ' (Dam olishda)' for a paused barber,
    and the strengthened AST test does not see it because the string goes through `text += f'...'` (AugAssign)."""
    sample_barber.is_paused = True
    owner = User(telegram_id=555001, first_name="Owner", language=lang, role=UserRole.OWNER.value)
    db_session.add(owner)
    await db_session.commit()

    call = MagicMock()
    call.data = "owner_back_to_barbers"
    call.answer = AsyncMock()
    call.message.edit_text = AsyncMock()
    await owner_handlers.handle_owner_back_to_barbers(call, db_session, owner, lang)

    shown = call.message.edit_text.await_args.args[0]
    assert "Dam olishda" not in shown, f"hard-coded Uzbek text shown to a '{lang}' owner: {shown!r}"
    assert t("owner.status_paused", lang=lang) in shown, f"translated paused marker missing for '{lang}': {shown!r}"


@pytest.mark.asyncio
async def test_Y3_customer_must_be_told_when_his_payment_could_not_be_recorded(
    session_factory, sample_barber, sample_clients, mock_notifier, monkeypatch
):
    """Telegram has already charged the card. If recording fails, the owner is alerted (fixed in round 3) but the customer only
    got the generic 'unexpected error, try later' from the error middleware, so he pays a second time. The customer must get a
    specific message (the payment was received and is being checked), not the generic error, from the successful-payment handler."""
    client = sample_clients[0]
    async with session_factory() as s:
        o = await QueueService(s, notifier=mock_notifier).join_queue(
            sample_barber.id, sample_barber.services[0].id, client, pay_now=True)
        await s.commit()
        order_id, price = o.id, o.price

    async def boom(self, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(PaymentService, "_execute_successful_payment", boom)

    message = MagicMock()
    message.successful_payment = SimpleNamespace(
        invoice_payload=f"order_{order_id}_CLICK", provider_payment_charge_id="tx-cust",
        telegram_payment_charge_id="tg-cust", total_amount=price * 100)
    message.from_user.id = client.telegram_id
    message.chat.id = client.telegram_id
    message.answer = AsyncMock()
    bot = MagicMock()
    bot.send_message = AsyncMock()

    async with session_factory() as s:
        try:
            await payment_handlers.handle_successful_payment_msg(message, s, bot)
        except Exception:
            pass  # re-raising is fine: the point is what the customer was told before that

    texts = []
    for c in message.answer.await_args_list:
        texts.append(str(c.args[0] if c.args else c.kwargs.get("text", "")))
    for c in bot.send_message.await_args_list:
        chat = c.kwargs.get("chat_id", c.args[0] if c.args else None)
        if chat == client.telegram_id:
            texts.append(str(c.kwargs.get("text", c.args[1] if len(c.args) > 1 else "")))
    generic = {t("common.error_generic", lang=lg) for lg in ("uz", "uz_cyrl", "ru")}
    specific = [x for x in texts if x.strip() and x not in generic]
    assert specific, f"the customer was charged and told nothing specific (texts sent to him: {texts})"


def test_Y4_requirements_lock_must_pin_every_runtime_dependency():
    """requirements.lock pins only part of the dependency tree. A fresh `pip install -r requirements.lock` on Python 3.12 still pulls
    these five at whatever version is newest that day, so the image is not reproducible."""
    pinned = {_norm(m.group(1)) for m in re.finditer(r"^([A-Za-z0-9_.\-]+)==", (ROOT / "requirements.lock").read_text(encoding="utf-8"), re.M)}
    missing = sorted({"aiofiles", "certifi", "pytz", "six", "tzlocal"} - pinned)
    assert not missing, f"requirements.lock does not pin: {missing}"
