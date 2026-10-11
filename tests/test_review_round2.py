"""Independent review, round 2. READ-ONLY: do not edit, rename, move or delete this file.
Every test asserts the CORRECT behaviour. A failure = a real defect.

PG-only tests need a real PostgreSQL: run with
    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db  python -m pytest tests/test_review_round2.py
They are SKIPPED on SQLite; the final report must show 0 skipped on the PostgreSQL run.
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, inspect as sa_inspect, select

from app.handlers import barber as barber_handlers
from app.models.enums import OrderStatus, PaymentStatus
from app.models.order import Order
from app.models.payment import Payment
from app.repositories.barber_repo import BarberRepository
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueService

ROOT = Path(__file__).resolve().parent.parent
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# token-shaped value built at run time so the source file itself holds no token-like literal (repo hygiene scan)
FAKE_BOT_TOKEN = "987654321:" + "AAH" + "x" * 35
pg_only = pytest.mark.skipif("postgresql" not in TEST_DB_URL, reason="needs real PostgreSQL (TEST_DATABASE_URL)")


# ----------------------------------------------------------------------------- helpers

@pytest.fixture(autouse=True)
def _fresh_process_local_locks():
    """QueueService keeps a class-level dict of asyncio.Lock objects. pytest gives every test its own event loop and a
    contended asyncio.Lock binds to the first loop that used it, so a lock reused by a later test raises
    'is bound to a different event loop'. Reset it so these tests do not depend on test order."""
    getattr(QueueService, "_barber_locks", {}).clear()
    yield


def make_call(data: str):
    c = MagicMock()
    c.data = data
    c.answer = AsyncMock()
    c.message.delete = AsyncMock()
    c.message.edit_text = AsyncMock()
    c.message.answer = AsyncMock()
    return c


def make_bot():
    b = MagicMock()
    b.send_message = AsyncMock()
    b.send_invoice = AsyncMock()
    return b


def pay_prompts(bot, tg_id):
    return [c for c in bot.send_message.call_args_list
            if c.kwargs.get("chat_id") == tg_id and c.kwargs.get("reply_markup") is not None]


async def order_status(session_factory, order_id):
    async with session_factory() as s:
        return (await s.execute(select(Order.status).where(Order.id == order_id))).scalar_one()


async def payment_rows(session_factory, order_id):
    async with session_factory() as s:
        return (await s.execute(
            select(Payment.method, Payment.provider_payment_id, Payment.status, Payment.refund_reason)
            .where(Payment.order_id == order_id).order_by(Payment.id))).all()


def parse_env_example() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ============================================================================ N1  payments lost under concurrency
@pg_only
@pytest.mark.asyncio
@pytest.mark.parametrize("n", [2, 5])
async def test_N1_parallel_payments_for_different_orders_of_one_barber_are_all_recorded(
    n, session_factory, sample_barber, sample_clients, mock_notifier
):
    ids = []
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        for c in sample_clients[:n]:
            o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, c, pay_now=True)
            ids.append((o.id, o.price))
        await s.commit()

    async def pay(i, oid, price):
        async with session_factory() as s:
            await PaymentService(s, notifier=mock_notifier).handle_successful_payment("CLICK", f"tx{i}", price, oid)
            await s.commit()

    results = await asyncio.gather(*[pay(i, oid, p) for i, (oid, p) in enumerate(ids)], return_exceptions=True)
    errors = [repr(r)[:120] for r in results if isinstance(r, Exception)]
    assert not errors, f"payments raised (money taken but not recorded): {errors}"

    async with session_factory() as s:
        paid = (await s.execute(select(func.count(Payment.id)).where(Payment.status == PaymentStatus.PAID.value))).scalar()
        pending = (await s.execute(select(func.count(Order.id)).where(Order.status == OrderStatus.PENDING_PAYMENT.value))).scalar()
    assert paid == n, f"{n} customers were charged but only {paid} payments were recorded"
    assert pending == 0, f"{pending} paid orders are still PENDING_PAYMENT (they will expire with no refund flag)"


@pg_only
@pytest.mark.asyncio
async def test_N1b_parallel_distinct_charges_for_one_order_both_recorded_one_paid(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async with session_factory() as s:
        o = await QueueService(s, notifier=mock_notifier).join_queue(
            sample_barber.id, sample_barber.services[0].id, sample_clients[0], pay_now=True)
        await s.commit()
        order_id, price = o.id, o.price

    async def pay(method, txid):
        async with session_factory() as s:
            await PaymentService(s, notifier=mock_notifier).handle_successful_payment(method, txid, price, order_id)
            await s.commit()

    results = await asyncio.gather(pay("CLICK", "txA"), pay("PAYME", "txB"), return_exceptions=True)
    errors = [repr(r)[:120] for r in results if isinstance(r, Exception)]
    assert not errors, f"a charge was lost: {errors}"
    rows = await payment_rows(session_factory, order_id)
    assert sorted(r[1] for r in rows) == ["txA", "txB"], f"both charges must be recorded, got {rows}"
    assert sum(1 for r in rows if r[2] == PaymentStatus.PAID.value) == 1, f"exactly one PAID expected: {rows}"
    assert sum(1 for r in rows if r[2] == PaymentStatus.REFUND_PENDING.value) == 1, f"the other must be REFUND_PENDING: {rows}"


# ============================================================================ R   stale read after lock (must stay green)
@pg_only
@pytest.mark.asyncio
async def test_R1_lateness_tick_must_not_overwrite_client_arrived(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        o1 = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])
        o2 = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[1])
        await s.commit()
        o1_id, o2_id = o1.id, o2.id
    assert await order_status(session_factory, o1_id) == OrderStatus.CALLED.value

    async with session_factory() as barber_sess:
        await QueueService(barber_sess, notifier=mock_notifier).client_arrived(o1_id)  # holds the lock, uncommitted

        async def tick():
            async with session_factory() as a:
                async with a.begin():
                    await QueueService(a, notifier=mock_notifier).handle_lateness(o1_id)

        task = asyncio.create_task(tick())
        await asyncio.sleep(1.0)
        assert not task.done(), "tick did not block on the barber lock - setup invalid"
        await barber_sess.commit()
        await asyncio.wait_for(task, 10)

    s1, s2 = await order_status(session_factory, o1_id), await order_status(session_factory, o2_id)
    assert s1 == OrderStatus.IN_SERVICE.value, f"client in the chair was overwritten to {s1} (next client: {s2})"


@pg_only
@pytest.mark.asyncio
async def test_R1b_cancelled_order_must_not_be_resurrected_by_stale_arrived(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async with session_factory() as s:
        o1 = await QueueService(s, notifier=mock_notifier).join_queue(
            sample_barber.id, sample_barber.services[0].id, sample_clients[0])
        await s.commit()
        o1_id = o1.id

    async with session_factory() as cancel_sess:
        await QueueService(cancel_sess, notifier=mock_notifier).cancel_by_staff(o1_id, staff_user_id=sample_barber.user_id)

        async def arrived():
            async with session_factory() as a:
                async with a.begin():
                    await QueueService(a, notifier=mock_notifier).client_arrived(o1_id)

        task = asyncio.create_task(arrived())
        await asyncio.sleep(1.0)
        assert not task.done()
        await cancel_sess.commit()
        await asyncio.wait_for(task, 10)

    assert await order_status(session_factory, o1_id) == OrderStatus.CANCELLED_BY_STAFF.value


@pg_only
@pytest.mark.asyncio
async def test_R4_five_parallel_joins_get_distinct_sequential_positions(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async def join(c):
        async with session_factory() as s:
            o = await QueueService(s, notifier=mock_notifier).join_queue(
                sample_barber.id, sample_barber.services[0].id, c)
            await s.commit()
            return o.position_key, o.ticket_no

    res = await asyncio.gather(*[join(c) for c in sample_clients])
    assert sorted(r[0] for r in res) == [1, 2, 3, 4, 5]
    assert sorted(r[1] for r in res) == [1, 2, 3, 4, 5]
    async with session_factory() as s:
        called = (await s.execute(select(func.count(Order.id)).where(Order.status == OrderStatus.CALLED.value))).scalar()
    assert called == 1


# ============================================================================ P1  lock query loads the whole history
@pytest.mark.asyncio
async def test_P1_locking_a_barber_must_not_load_all_his_orders_and_payments(
    session_factory, sample_barber
):
    """Measured: lock_barber_for_update() took 38 ms with no history, 187 ms with 1000 orders+payments, 1134 ms with 4000
    (Barber.orders / Barber.payments are lazy='selectin' and the lock query uses populate_existing)."""
    async with session_factory() as s:
        barber = await BarberRepository(s).lock_barber_for_update(sample_barber.id)
        unloaded = sa_inspect(barber).unloaded
    assert "orders" in unloaded and "payments" in unloaded, "the barber lock query loads every order and payment ever made"


# ============================================================================ S   stale Telegram buttons / double taps
@pytest.mark.asyncio
async def test_S1_stale_done_on_cancelled_order_must_not_prompt_client_to_pay(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])
    await qs.cancel_by_staff(o.id, sample_barber.user_id)
    await db_session.commit()
    bot = make_bot()
    await barber_handlers.handle_b_done(make_call(f"b_done:{o.id}"), db_session, sample_barber.user, bot, "uz")
    assert not pay_prompts(bot, sample_clients[0].telegram_id), "client of a CANCELLED order was asked to pay"


@pytest.mark.asyncio
async def test_S2_double_tap_done_must_prompt_client_once(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])
    await qs.client_arrived(o.id)
    await db_session.commit()
    bot = make_bot()
    for _ in range(2):
        await barber_handlers.handle_b_done(make_call(f"b_done:{o.id}"), db_session, sample_barber.user, bot, "uz")
    assert len(pay_prompts(bot, sample_clients[0].telegram_id)) == 1


@pytest.mark.asyncio
async def test_S3_stale_cash_on_cancelled_order_must_not_create_a_refund_row(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])
    await qs.cancel_by_staff(o.id, sample_barber.user_id)
    await db_session.commit()
    await barber_handlers.handle_b_cash(make_call(f"b_cash:{o.id}"), db_session, sample_barber.user, make_bot(), "uz")
    rows = (await db_session.execute(select(Payment.status).where(Payment.order_id == o.id))).all()
    assert rows == [], f"cash tap on a cancelled order produced {rows}"


@pytest.mark.asyncio
async def test_S4_cash_on_an_order_not_yet_served_must_be_rejected(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])  # CALLED, not served
    await db_session.commit()
    await barber_handlers.handle_b_cash(make_call(f"b_cash:{o.id}"), db_session, sample_barber.user, make_bot(), "uz")
    rows = (await db_session.execute(select(Payment.status).where(Payment.order_id == o.id))).all()
    assert rows == [], f"cash recorded as {rows} for an order that was never served"


@pytest.mark.asyncio
async def test_S5_cash_button_double_tap_is_idempotent(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])
        await qs.client_arrived(o.id)
        await qs.complete_service(o.id)
        await s.commit()
        order_id = o.id
    for _ in range(2):
        async with session_factory() as s:
            await PaymentService(s, notifier=mock_notifier).confirm_cash_payment(order_id, sample_barber.user_id)
            await s.commit()
        await asyncio.sleep(1.1)  # second tap lands in a different second
    rows = await payment_rows(session_factory, order_id)
    assert [r[2] for r in rows] == [PaymentStatus.PAID.value], f"double tap produced {rows}"


# ============================================================================ E   configuration
def test_E1_env_example_must_load_without_crashing():
    from app.config import Settings
    s = Settings(_env_file=str(ROOT / ".env.example"))
    assert len(s.OWNER_TELEGRAM_IDS) >= 1 and all(isinstance(i, int) for i in s.OWNER_TELEGRAM_IDS)
    assert "CASH" in s.ENABLED_PAYMENT_METHODS


@pytest.mark.parametrize("owners,methods,expect_owners,expect_methods", [
    ("555111222", "CASH", [555111222], ["CASH"]),
    ("555111222,666", "CASH,CLICK", [555111222, 666], ["CASH", "CLICK"]),
    ("555111222, 666", "cash, click", [555111222, 666], ["CASH", "CLICK"]),
])
def test_E1b_comma_separated_lists_in_env_must_parse(monkeypatch, owners, methods, expect_owners, expect_methods):
    from app.config import Settings
    monkeypatch.setenv("OWNER_TELEGRAM_IDS", owners)
    monkeypatch.setenv("ENABLED_PAYMENT_METHODS", methods)
    s = Settings(_env_file=None)
    assert s.OWNER_TELEGRAM_IDS == expect_owners
    assert s.ENABLED_PAYMENT_METHODS == expect_methods


def _prod_kwargs(**over):
    kw = dict(
        _env_file=None, ENV="production", PAYMENTS_MODE="live", OWNER_TELEGRAM_IDS=[555111222],
        BOT_TOKEN=FAKE_BOT_TOKEN,
        WEBHOOK_SECRET="a" * 40, WEBHOOK_PATH_SECRET="b" * 40, CRON_SECRET="c" * 40,
        CLICK_PROVIDER_TOKEN="398061295:LIVE:abcdef", PAYME_PROVIDER_TOKEN="371317599:LIVE:ghijkl",
        ENABLED_PAYMENT_METHODS=["CASH", "CLICK", "PAYME"],
        DATABASE_URL="postgresql+asyncpg://u:p@db:5432/x",
    )
    kw.update(over)
    return kw


def test_E2_production_accepts_a_fully_valid_configuration():
    from app.config import Settings
    Settings(**_prod_kwargs()).validate_runtime()


def test_E2a_production_rejects_every_value_copied_from_env_example():
    from app.config import Settings
    ex = parse_env_example()
    for key in ("WEBHOOK_SECRET", "WEBHOOK_PATH_SECRET", "CRON_SECRET"):
        with pytest.raises(ValueError):
            Settings(**_prod_kwargs(**{key: ex[key]})).validate_runtime()
    example_owner_ids = [int(x) for x in ex["OWNER_TELEGRAM_IDS"].split(",")]
    for oid in example_owner_ids:
        with pytest.raises(ValueError):
            Settings(**_prod_kwargs(OWNER_TELEGRAM_IDS=[555111222, oid])).validate_runtime()
    with pytest.raises(ValueError):
        Settings(**_prod_kwargs(BOT_TOKEN=ex["BOT_TOKEN"])).validate_runtime()


@pytest.mark.parametrize("over", [
    dict(CLICK_PROVIDER_TOKEN="398061295:TEST:99999"),
    dict(PAYME_PROVIDER_TOKEN="371317599:TEST:11111"),
    dict(CLICK_PROVIDER_TOKEN=""),
    dict(PAYME_PROVIDER_TOKEN=""),
])
def test_E2b_live_mode_rejects_test_or_empty_provider_tokens_for_enabled_methods(over):
    from app.config import Settings
    with pytest.raises(ValueError):
        Settings(**_prod_kwargs(**over)).validate_runtime()


# ============================================================================ B   build / install / migrations
def test_B1_requirements_must_make_a_fresh_install_importable():
    """A fresh venv resolved SQLAlchemy 2.1.x, which no longer pulls greenlet: `import app.main` died with
    'The SQLAlchemy asyncio module requires that the Python greenlet library is installed'."""
    txt = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert re.search(r"sqlalchemy\[[^\]]*asyncio[^\]]*\]", txt) or re.search(r"^greenlet", txt, re.M), \
        "requirements.txt must contain sqlalchemy[asyncio] or greenlet"


def test_B2_make_test_pg_must_really_point_the_tests_at_postgres():
    """conftest.py reads TEST_DATABASE_URL only; the old target set DATABASE_URL, so 'make test-pg' silently ran on SQLite."""
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    m = re.search(r"^test-pg:.*?(?=^\S|\Z)", mk, re.M | re.S)
    assert m and "TEST_DATABASE_URL" in m.group(0), "make test-pg does not set TEST_DATABASE_URL"


def test_B3_alembic_check_must_report_no_drift_between_models_and_migrations():
    """On a database built by `alembic upgrade head`, `alembic check` reported 14 differences
    (missing indexes such as ix_orders_status, ix_payments_order_id, ix_payments_status, ix_audit_log_actor_user_id ...)."""
    from alembic import command
    from alembic.config import Config

    with tempfile.TemporaryDirectory() as d:
        db_url = f"sqlite:///{d}/drift.db"
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = db_url
        try:
            cfg = Config(str(ROOT / "alembic.ini"))
            cfg.set_main_option("script_location", str(ROOT / "migrations"))
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
            command.check(cfg)  # raises CommandError when models and migrations differ
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
