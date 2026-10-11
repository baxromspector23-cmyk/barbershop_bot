"""Review tests: each one asserts the CORRECT behaviour required by the spec.
A failing test here = a real defect in the delivered code."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select

from app.config import Settings, settings
from app.handlers import barber as barber_handlers
from app.handlers import client as client_handlers
from app.handlers import payments as payment_handlers
from app.models.enums import OrderStatus, UserRole
from app.models.payment import Payment
from app.models.service import Service
from app.models.user import User
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.services.due_work_service import process_due_work
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueService
from app.utils.time_utils import tashkent_today


def make_call(data: str):
    call = MagicMock()
    call.data = data
    call.answer = AsyncMock()
    call.message.delete = AsyncMock()
    call.message.edit_text = AsyncMock()
    call.message.edit_reply_markup = AsyncMock()
    call.message.answer = AsyncMock()
    return call


def make_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_invoice = AsyncMock()
    return bot


async def paid_count(session, order_id: int) -> int:
    res = await session.execute(
        select(func.count(Payment.id)).where(Payment.order_id == order_id)
    )
    return res.scalar() or 0


# F1 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_F1_prepaid_client_must_not_be_asked_to_pay_again(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    client = sample_clients[0]
    order = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, client, pay_now=True)
    ps = PaymentService(db_session, notifier=mock_notifier)
    await ps.handle_successful_payment("CLICK", "tx1", order.price, order.id)
    await qs.client_arrived(order.id)
    await db_session.commit()

    bot = make_bot()
    await barber_handlers.handle_b_done(
        make_call(f"b_done:{order.id}"), db_session, sample_barber.user, bot, "uz"
    )
    prompts = [
        c for c in bot.send_message.call_args_list
        if c.kwargs.get("chat_id") == client.telegram_id and c.kwargs.get("reply_markup") is not None
    ]
    assert not prompts, "already-paid client received a 'pay now' keyboard after service"


# F2 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_F2_foreign_barber_cannot_mark_cash_for_other_barbers_order(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    order = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])
    intruder = User(telegram_id=999001, first_name="Other", role=UserRole.BARBER.value, language="uz")
    db_session.add(intruder)
    await db_session.commit()

    await barber_handlers.handle_b_cash(
        make_call(f"b_cash:{order.id}"), db_session, intruder, make_bot(), "uz"
    )
    assert await paid_count(db_session, order.id) == 0, "another barber recorded a payment on this order"


# F3 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_F3_foreign_barber_cannot_cancel_other_barbers_order(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    order = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])
    intruder = User(telegram_id=999002, first_name="Other", role=UserRole.BARBER.value, language="uz")
    db_session.add(intruder)
    await db_session.commit()

    await barber_handlers.handle_b_cancel(
        make_call(f"b_cancel:{order.id}"), db_session, intruder, make_bot(), "uz"
    )
    reloaded = await OrderRepository(db_session).get_by_id(order.id)
    assert reloaded.status == OrderStatus.CALLED.value, f"order became {reloaded.status}"


# F4 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_F4_fake_payment_must_not_work_in_live_mode(
    db_session, sample_barber, sample_clients, mock_notifier, monkeypatch
):
    monkeypatch.setattr(settings, "PAYMENTS_MODE", "live")
    monkeypatch.setattr(settings, "ENV", "production")
    qs = QueueService(db_session, notifier=mock_notifier)
    order = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0], pay_now=True)
    await db_session.commit()

    stranger = sample_clients[1]  # not even the order's owner
    await client_handlers.handle_pay_method_selected(
        make_call(f"pay_method:{order.id}:FAKE"), db_session, make_bot(), stranger, "uz"
    )
    reloaded = await OrderRepository(db_session).get_by_id(order.id)
    assert reloaded.status == OrderStatus.PENDING_PAYMENT.value, "order got activated by a FAKE payment in live mode"


# F5 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_F5a_second_charge_must_be_kept_as_its_own_record(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    order = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0], pay_now=True)
    ps = PaymentService(db_session, notifier=mock_notifier)
    await ps.handle_successful_payment("CLICK", "tx1", order.price, order.id)
    await ps.handle_successful_payment("PAYME", "tx2", order.price, order.id)
    await db_session.commit()
    assert await paid_count(db_session, order.id) == 2, "second charge overwrote the first payment row"


@pytest.mark.asyncio
async def test_F5b_pre_checkout_must_reject_already_paid_order(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    order = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0], pay_now=True)
    ps = PaymentService(db_session, notifier=mock_notifier)
    await ps.handle_successful_payment("CLICK", "tx1", order.price, order.id)
    await db_session.commit()

    query = MagicMock()
    query.invoice_payload = f"order_{order.id}_CLICK"
    query.total_amount = order.price * 100
    query.answer = AsyncMock()
    await payment_handlers.handle_pre_checkout(query, db_session)
    assert query.answer.call_args.kwargs.get("ok") is False, "Telegram was told to charge an already-paid order"


# F6 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_F6_stale_in_service_order_reported_once_not_every_tick(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])
        await qs.client_arrived(o.id)
        o.ticket_date = tashkent_today() - timedelta(days=1)
        o.started_at = None  # sidestep the separate SQLite naive-datetime crash (see F10)
        await s.commit()

    owner = 777001
    for _ in range(3):
        await process_due_work(session_factory, notifier=mock_notifier, owner_telegram_ids=[owner])
    sent = [e for e in mock_notifier.sent_events if e["telegram_id"] == owner]
    assert len(sent) == 1, f"owner received {len(sent)} identical alerts in 3 ticks"


# F7 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_F7_end_of_day_expiry_of_prepaid_order_must_flag_refund(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0], pay_now=True)
        await PaymentService(s, notifier=mock_notifier).handle_successful_payment("CLICK", "tx1", o.price, o.id)
        o.ticket_date = tashkent_today() - timedelta(days=1)
        await s.commit()
        oid = o.id

    await process_due_work(session_factory, notifier=mock_notifier, owner_telegram_ids=[])
    async with session_factory() as s:
        order = await OrderRepository(s).get_by_id(oid)
        pay = await PaymentRepository(s).get_by_order_id(oid)
        assert order.status == OrderStatus.EXPIRED.value
        assert pay.status == "REFUND_PENDING", f"customer money is {pay.status}, owner never told to refund"


# F8 -------------------------------------------------------------------------
def test_F8_production_must_refuse_default_secrets_and_default_owner():
    s = Settings(_env_file=None, ENV="production", PAYMENTS_MODE="live")
    with pytest.raises(ValueError):
        s.validate_runtime()


# F10 ------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_F10a_queue_metrics_work_while_a_client_is_in_service(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    order = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])
    await qs.client_arrived(order.id)
    await db_session.commit()
    db_session.expire_all()  # next screen opens in a fresh request
    await qs.get_barber_queue_metrics(sample_barber.id)


@pytest.mark.asyncio
async def test_F10b_due_work_survives_an_in_service_order(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0])
        await qs.client_arrived(o.id)
        await s.commit()
    await process_due_work(session_factory, notifier=mock_notifier, owner_telegram_ids=[])


# F9 -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_F9_barber_cannot_toggle_other_barbers_service(
    db_session, sample_barber, mock_notifier
):
    svc_id = sample_barber.services[0].id
    intruder = User(telegram_id=999003, first_name="Other", role=UserRole.BARBER.value, language="uz")
    db_session.add(intruder)
    await db_session.commit()
    try:
        await barber_handlers.handle_toggle_service(
            make_call(f"toggle_svc:{svc_id}"), db_session, intruder, "uz"
        )
    except Exception:
        pass  # handler later crashes (intruder has no barber profile) but the toggle is already committed
    await db_session.rollback()
    svc = (await db_session.execute(select(Service).where(Service.id == svc_id))).scalar_one()
    assert svc.is_active is True, "service of another barber was switched off"
