"""Manual card-transfer payments (TRANSFER), queue capacity and ETA. Runs on SQLite; the parallel tests also run on PostgreSQL."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select

from app.config import Settings, settings
from app.handlers import barber as barber_handlers
from app.handlers import client as client_handlers
from app.models.barber import Barber
from app.models.enums import Language, OrderStatus, PaymentStatus, UserRole
from app.models.order import Order
from app.models.payment import Payment
from app.models.user import User
from app.repositories.payment_repo import PaymentRepository
from app.services.authorization import AuthorizationError
from app.services.manual_payment_service import (
    AlreadyPaidError,
    DuplicateReceiptError,
    ManualPaymentService,
    NothingToConfirmError,
    OrderNotPayableError,
)
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueFullError, QueueService
from app.utils.time_utils import TASHKENT_TZ

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
pg_only = pytest.mark.skipif("postgresql" not in TEST_DB_URL, reason="needs real PostgreSQL")
OWNER_TG = 990001
STAFF_BARBER_TG = 111111  # sample_barber's telegram id


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    getattr(QueueService, "_barber_locks", {}).clear()
    monkeypatch.setattr(settings, "OWNER_TELEGRAM_IDS", [OWNER_TG])
    yield


async def _join(session_factory, barber, client, notifier, service_index=0):
    async with session_factory() as s:
        o = await QueueService(s, notifier=notifier).join_queue(
            barber.id, barber.services[service_index].id, client, pay_now=False)
        await s.commit()
        return o.id


async def _submit(session_factory, order_id, client, notifier, unique="uniq-1"):
    async with session_factory() as s:
        svc = ManualPaymentService(s, notifier=notifier)
        p = await svc.submit_receipt(order_id, client.id, f"file-{unique}", unique)
        await s.commit()
        return p.id


async def _staff(session_factory, telegram_id):
    async with session_factory() as s:
        u = (await s.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()
        b = (await s.execute(select(Barber).where(Barber.user_id == u.id))).scalar_one_or_none()
        return u, b


async def _make_other_barber(session_factory):
    async with session_factory() as s:
        u = User(telegram_id=222222, first_name="Other", language=Language.UZ.value, role=UserRole.BARBER.value)
        s.add(u)
        await s.flush()
        s.add(Barber(user_id=u.id, display_name="Other Barber", is_active=True, is_paused=False))
        await s.commit()


async def _make_owner(session_factory):
    async with session_factory() as s:
        s.add(User(telegram_id=OWNER_TG, first_name="Owner", language=Language.RU.value, role=UserRole.OWNER.value))
        await s.commit()


async def _payments(session_factory, order_id):
    async with session_factory() as s:
        return (await s.execute(select(Payment).where(Payment.order_id == order_id).order_by(Payment.id))).scalars().all()


# ----------------------------------------------------------------------------- happy path
@pytest.mark.asyncio
async def test_M1_receipt_is_sent_to_the_serving_barber_confirmed_and_counted_as_his_revenue(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier)

    async with session_factory() as s:
        svc = ManualPaymentService(s, notifier=mock_notifier)
        assert await svc.notify_receipt_submitted(pid)
    photo_events = [e for e in mock_notifier.sent_events if e.get("photo")]
    assert photo_events and photo_events[-1]["telegram_id"] == STAFF_BARBER_TG
    assert photo_events[-1]["photo"] == "file-uniq-1"
    buttons = [b.callback_data for row in photo_events[-1]["reply_markup"].inline_keyboard for b in row]
    assert buttons == [f"tr_ok:{pid}", f"tr_no:{pid}"]
    assert "client_1" in photo_events[-1]["text"] and "so'm so'm" not in photo_events[-1]["text"]  # the barber sees WHO paid

    staff, barber = await _staff(session_factory, STAFF_BARBER_TG)
    async with session_factory() as s:
        res = await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, staff, barber=barber)
        await s.commit()
    assert res.changed and not res.refund_flagged
    assert res.payment.status == PaymentStatus.PAID.value and res.payment.confirmed_by_user_id == staff.id
    assert res.payment.barber_id == sample_barber.id

    # revenue counts only after the service is completed
    async with session_factory() as s:
        now = datetime.now(TASHKENT_TZ)
        start, end = now - timedelta(days=1), now + timedelta(days=1)
        assert await PaymentRepository(s).get_barber_revenue_in_range(sample_barber.id, start, end) == 0
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        await qs.client_arrived(oid)
        await s.commit()
        await qs.complete_service(oid)
        await s.commit()
    async with session_factory() as s:
        assert await PaymentRepository(s).get_barber_revenue_in_range(sample_barber.id, start, end) == sample_barber.services[0].price


@pytest.mark.asyncio
async def test_M2_another_barber_cannot_confirm_or_reject(session_factory, sample_barber, sample_clients, mock_notifier):
    await _make_other_barber(session_factory)
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier)
    other, other_barber = await _staff(session_factory, 222222)
    for action in ("confirm", "reject"):
        async with session_factory() as s:
            svc = ManualPaymentService(s, notifier=mock_notifier)
            with pytest.raises(AuthorizationError):
                if action == "confirm":
                    await svc.confirm_transfer(pid, other, barber=other_barber)
                else:
                    await svc.reject_transfer(pid, other, "UNCLEAR", barber=other_barber)
    assert (await _payments(session_factory, oid))[0].status == PaymentStatus.RECEIPT_SENT.value


@pytest.mark.asyncio
async def test_M2b_a_client_cannot_confirm_his_own_payment(session_factory, sample_barber, sample_clients, mock_notifier):
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier)
    async with session_factory() as s:
        with pytest.raises(AuthorizationError):
            await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, client, barber=None)


@pytest.mark.asyncio
async def test_M3_the_owner_may_confirm_any_receipt(session_factory, sample_barber, sample_clients, mock_notifier):
    await _make_owner(session_factory)
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier)
    owner, _ = await _staff(session_factory, OWNER_TG)
    async with session_factory() as s:
        res = await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, owner, barber=None)
        await s.commit()
    assert res.changed and res.payment.status == PaymentStatus.PAID.value


# ----------------------------------------------------------------------------- receipts
@pytest.mark.asyncio
async def test_M4_one_receipt_photo_cannot_back_two_orders(session_factory, sample_barber, sample_clients, mock_notifier):
    o1 = await _join(session_factory, sample_barber, sample_clients[0], mock_notifier)
    o2 = await _join(session_factory, sample_barber, sample_clients[1], mock_notifier)
    await _submit(session_factory, o1, sample_clients[0], mock_notifier, unique="same-photo")
    with pytest.raises(DuplicateReceiptError):
        await _submit(session_factory, o2, sample_clients[1], mock_notifier, unique="same-photo")
    assert await _payments(session_factory, o2) == []


@pytest.mark.asyncio
async def test_M5_nobody_can_pay_for_someone_elses_order(session_factory, sample_barber, sample_clients, mock_notifier):
    o1 = await _join(session_factory, sample_barber, sample_clients[0], mock_notifier)
    with pytest.raises(OrderNotPayableError):
        await _submit(session_factory, o1, sample_clients[1], mock_notifier)


@pytest.mark.asyncio
async def test_M6_reject_then_resend_then_confirm(session_factory, sample_barber, sample_clients, mock_notifier):
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier, unique="blurry")
    staff, barber = await _staff(session_factory, STAFF_BARBER_TG)

    async with session_factory() as s:
        svc = ManualPaymentService(s, notifier=mock_notifier)
        res = await svc.reject_transfer(pid, staff, "UNCLEAR", barber=barber)
        await s.commit()
        assert res.changed and res.payment.status == PaymentStatus.REJECTED.value
        await svc.notify_client_rejected(res.payment, "UNCLEAR")
    msg = [e for e in mock_notifier.sent_events if e["telegram_id"] == client.telegram_id][-1]
    assert msg["reply_markup"].inline_keyboard[0][0].callback_data == f"tr_send:{oid}"  # client can resend at once

    async with session_factory() as s:  # confirming a rejected receipt is not possible
        with pytest.raises(NothingToConfirmError):
            await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, staff, barber=barber)

    pid2 = await _submit(session_factory, oid, client, mock_notifier, unique="clear")
    assert pid2 == pid  # same payment row, one per order
    async with session_factory() as s:
        res = await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, staff, barber=barber)
        await s.commit()
    rows = await _payments(session_factory, oid)
    assert len(rows) == 1 and rows[0].status == PaymentStatus.PAID.value
    assert rows[0].raw_payload["rejections"][0]["reason"] == "UNCLEAR"


@pytest.mark.asyncio
async def test_M7_double_confirm_records_the_money_once(session_factory, sample_barber, sample_clients, mock_notifier):
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier)
    staff, barber = await _staff(session_factory, STAFF_BARBER_TG)
    changed = []
    for _ in range(2):
        async with session_factory() as s:
            res = await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, staff, barber=barber)
            await s.commit()
            changed.append(res.changed)
    assert changed == [True, False]
    async with session_factory() as s:
        n = (await s.execute(select(func.count(Payment.id)).where(Payment.status == PaymentStatus.PAID.value))).scalar()
    assert n == 1


@pg_only
@pytest.mark.asyncio
async def test_M7b_parallel_confirm_by_barber_and_owner_records_the_money_once(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    await _make_owner(session_factory)
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier)
    barber_user, barber = await _staff(session_factory, STAFF_BARBER_TG)
    owner, _ = await _staff(session_factory, OWNER_TG)

    async def confirm(user, b):
        async with session_factory() as s:
            res = await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, user, barber=b)
            await s.commit()
            return res.changed

    results = await asyncio.gather(confirm(barber_user, barber), confirm(owner, None), return_exceptions=True)
    assert not [r for r in results if isinstance(r, Exception)], results
    assert sorted(results) == [False, True]
    assert [p.status for p in await _payments(session_factory, oid)] == [PaymentStatus.PAID.value]


@pg_only
@pytest.mark.asyncio
async def test_M7c_parallel_confirm_and_cancel_never_lose_or_invent_money(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    # the client is second in line so that cancelling is allowed (first client is CALLED, cancel is allowed too)
    pid = await _submit(session_factory, oid, client, mock_notifier)
    staff, barber = await _staff(session_factory, STAFF_BARBER_TG)

    async def confirm():
        async with session_factory() as s:
            await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, staff, barber=barber)
            await s.commit()

    async def cancel():
        async with session_factory() as s:
            await QueueService(s, notifier=mock_notifier).cancel_by_client(oid, client.id)
            await s.commit()

    res = await asyncio.gather(confirm(), cancel(), return_exceptions=True)
    errors = [r for r in res if isinstance(r, Exception) and not isinstance(r, NothingToConfirmError)]
    assert not errors, errors
    rows = await _payments(session_factory, oid)
    assert len(rows) == 1
    # whichever won, a cancelled order must never keep a PAID/RECEIPT_SENT payment: the money must be flagged for refund
    assert rows[0].status == PaymentStatus.REFUND_PENDING.value, rows[0].status


# ----------------------------------------------------------------------------- money edge cases
@pytest.mark.asyncio
async def test_M8_cancelling_an_order_with_an_unverified_receipt_flags_it_for_refund_and_tells_the_owner(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    await _make_owner(session_factory)
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    await _submit(session_factory, oid, client, mock_notifier)
    async with session_factory() as s:
        await QueueService(s, notifier=mock_notifier).cancel_by_client(oid, client.id)
        await s.commit()
    rows = await _payments(session_factory, oid)
    assert rows[0].status == PaymentStatus.REFUND_PENDING.value
    assert [e for e in mock_notifier.sent_events if e["telegram_id"] == OWNER_TG]


@pytest.mark.asyncio
async def test_M9_confirming_a_receipt_for_a_dead_order_becomes_a_refund_not_revenue(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    await _make_owner(session_factory)
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier)
    async with session_factory() as s:  # order died without going through cancel (e.g. an old row)
        (await s.get(Order, oid)).status = OrderStatus.EXPIRED.value
        await s.commit()
    staff, barber = await _staff(session_factory, STAFF_BARBER_TG)
    async with session_factory() as s:
        res = await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, staff, barber=barber)
        await s.commit()
    assert res.refund_flagged and res.payment.status == PaymentStatus.REFUND_PENDING.value
    assert [e for e in mock_notifier.sent_events if e["telegram_id"] == OWNER_TG]


@pytest.mark.asyncio
async def test_M10_transfer_confirmed_after_cash_was_taken_is_flagged_as_duplicate(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    await _make_owner(session_factory)
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier)
    staff, barber = await _staff(session_factory, STAFF_BARBER_TG)
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        await qs.client_arrived(oid)
        await s.commit()
        await qs.complete_service(oid)
        await s.commit()
    async with session_factory() as s:
        await PaymentService(s, notifier=mock_notifier).confirm_cash_payment(oid, staff.id)
        await s.commit()
    async with session_factory() as s:
        res = await ManualPaymentService(s, notifier=mock_notifier).confirm_transfer(pid, staff, barber=barber)
        await s.commit()
    assert res.refund_flagged and res.payment.refund_reason == "DUPLICATE_PAYMENT"
    statuses = sorted(p.status for p in await _payments(session_factory, oid))
    assert statuses == [PaymentStatus.PAID.value, PaymentStatus.REFUND_PENDING.value]


@pytest.mark.asyncio
async def test_M11_no_receipt_after_the_order_is_paid(session_factory, sample_barber, sample_clients, mock_notifier):
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    staff, _ = await _staff(session_factory, STAFF_BARBER_TG)
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        await qs.client_arrived(oid)
        await s.commit()
        await qs.complete_service(oid)
        await s.commit()
    async with session_factory() as s:
        await PaymentService(s, notifier=mock_notifier).confirm_cash_payment(oid, staff.id)
        await s.commit()
    with pytest.raises(AlreadyPaidError):
        await _submit(session_factory, oid, client, mock_notifier)


# ----------------------------------------------------------------------------- Telegram handlers
def _call(data, user_id):
    from aiogram.types import CallbackQuery
    c = MagicMock(spec=CallbackQuery)
    c.data = data
    c.from_user = MagicMock()
    c.from_user.id = user_id
    c.answer = AsyncMock()
    c.message = MagicMock()
    c.message.edit_text = AsyncMock()
    c.message.edit_reply_markup = AsyncMock()
    c.message.answer = AsyncMock()
    c.message.answer_photo = AsyncMock()
    c.message.delete = AsyncMock()
    return c


def _bot():
    b = MagicMock()
    b.send_message = AsyncMock()
    b.send_photo = AsyncMock()
    return b


@pytest.mark.asyncio
async def test_M12_whole_telegram_flow_client_photo_to_barber_confirm_to_client_message(
    session_factory, sample_barber, sample_clients, monkeypatch
):
    monkeypatch.setattr(settings, "PAYMENT_CARD_NUMBER", "8600123412341234")
    monkeypatch.setattr(settings, "PAYMENT_CARD_HOLDER", "TEST HOLDER")
    monkeypatch.setattr(settings, "ENABLED_PAYMENT_METHODS", ["CASH", "TRANSFER"])
    client = sample_clients[0]
    bot = _bot()
    notifier = MagicMock()
    oid = await _join(session_factory, sample_barber, client, __import__("app.services.notification_service", fromlist=["x"]).NotificationService())

    # 1) client picks "card transfer": sees the card, the holder and the amount
    async with session_factory() as s:
        call = _call(f"pay_method:{oid}:TRANSFER", client.telegram_id)
        await client_handlers.handle_pay_method_selected(call, s, bot, client, "uz")
    text = call.message.edit_text.await_args.args[0]
    assert "8600 1234 1234 1234" in text and "TEST HOLDER" in text and "50" in text

    # 2) client presses "send receipt" then sends a photo
    state = MagicMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.clear = AsyncMock()
    state.get_data = AsyncMock(return_value={"receipt_order_id": oid})
    async with session_factory() as s:
        await client_handlers.handle_receipt_send_prompt(_call(f"tr_send:{oid}", client.telegram_id), s, client, state, "uz")
    state.set_state.assert_awaited()

    msg = MagicMock()
    msg.photo = [MagicMock(file_id="small", file_unique_id="u-small"), MagicMock(file_id="big-file", file_unique_id="u-big")]
    msg.answer = AsyncMock()
    async with session_factory() as s:
        await client_handlers.handle_receipt_photo(msg, s, client, bot, state, "uz")
    assert bot.send_photo.await_count == 1
    kw = bot.send_photo.await_args.kwargs
    assert kw["chat_id"] == STAFF_BARBER_TG and kw["photo"] == "big-file"  # the biggest photo goes to the barber
    ok_cb = kw["reply_markup"].inline_keyboard[0][0].callback_data
    assert ok_cb.startswith("tr_ok:")

    # 3) the barber presses Confirm: client gets a message, buttons disappear
    barber_user, _ = await _staff(session_factory, STAFF_BARBER_TG)
    async with session_factory() as s:
        barber_user = (await s.execute(select(User).where(User.telegram_id == STAFF_BARBER_TG))).scalar_one()
        call = _call(ok_cb, STAFF_BARBER_TG)
        await barber_handlers.handle_transfer_confirm(call, s, barber_user, bot, "uz")
    call.message.edit_reply_markup.assert_awaited()
    sent_to_client = [c for c in bot.send_message.await_args_list if c.kwargs.get("chat_id") == client.telegram_id]
    assert sent_to_client, "the client was not told that his payment was confirmed"
    assert [p.status for p in await _payments(session_factory, oid)] == [PaymentStatus.PAID.value]
    del notifier


@pytest.mark.asyncio
async def test_M13_a_foreign_barber_pressing_confirm_gets_an_alert_and_nothing_changes(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    await _make_other_barber(session_factory)
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier)
    async with session_factory() as s:
        other = (await s.execute(select(User).where(User.telegram_id == 222222))).scalar_one()
        call = _call(f"tr_ok:{pid}", 222222)
        await barber_handlers.handle_transfer_confirm(call, s, other, _bot(), "uz")
    assert call.answer.await_args.kwargs.get("show_alert") is True
    assert (await _payments(session_factory, oid))[0].status == PaymentStatus.RECEIPT_SENT.value


@pytest.mark.asyncio
async def test_M14_transfer_without_a_configured_card_is_refused(session_factory, sample_barber, sample_clients, mock_notifier, monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_CARD_NUMBER", "")
    monkeypatch.setattr(settings, "ENABLED_PAYMENT_METHODS", ["CASH", "TRANSFER"])
    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    async with session_factory() as s:
        call = _call(f"pay_method:{oid}:TRANSFER", client.telegram_id)
        await client_handlers.handle_pay_method_selected(call, s, _bot(), client, "uz")
    assert call.answer.await_args.kwargs.get("show_alert") is True
    call.message.edit_text.assert_not_awaited()


# ----------------------------------------------------------------------------- capacity and ETA
@pytest.mark.asyncio
async def test_M20_queue_is_capped_per_barber(session_factory, sample_barber, sample_clients, mock_notifier, monkeypatch):
    monkeypatch.setattr(settings, "MAX_QUEUE_PER_BARBER", 2)
    await _join(session_factory, sample_barber, sample_clients[0], mock_notifier)
    await _join(session_factory, sample_barber, sample_clients[1], mock_notifier)
    with pytest.raises(QueueFullError) as exc:
        await _join(session_factory, sample_barber, sample_clients[2], mock_notifier)
    assert exc.value.reason == "MAX_QUEUE"


@pytest.mark.asyncio
async def test_M21_a_client_who_cannot_be_served_before_closing_is_not_accepted(
    session_factory, sample_barber, sample_clients, mock_notifier, monkeypatch
):
    monkeypatch.setattr(settings, "CHECK_WORKING_HOURS", True)
    # working hours in the fixture are 00:00-23:59; pretend it is 23:30 (29 minutes left)
    fake_now = datetime.now(TASHKENT_TZ).replace(hour=23, minute=30, second=0, microsecond=0)
    monkeypatch.setattr("app.services.queue_service.now_tashkent", lambda: fake_now)
    long_service = sample_barber.services[0]   # 30 minutes
    short_service = sample_barber.services[1]  # 20 minutes
    assert long_service.duration_minutes == 30 and short_service.duration_minutes == 20
    async with session_factory() as s:
        with pytest.raises(QueueFullError) as exc:
            await QueueService(s, notifier=mock_notifier).join_queue(sample_barber.id, long_service.id, sample_clients[0])
        assert exc.value.reason == "CLOSING_SOON"
    # a 20 minute service still fits
    async with session_factory() as s:
        await QueueService(s, notifier=mock_notifier).join_queue(sample_barber.id, short_service.id, sample_clients[0])
        await s.commit()
    # but then the next client does not (20 + 20 > 29)
    async with session_factory() as s:
        with pytest.raises(QueueFullError):
            await QueueService(s, notifier=mock_notifier).join_queue(sample_barber.id, short_service.id, sample_clients[1])


@pytest.mark.asyncio
async def test_M22_barber_can_still_add_a_walkin_when_the_queue_is_full(session_factory, sample_barber, sample_clients, mock_notifier, monkeypatch):
    monkeypatch.setattr(settings, "MAX_QUEUE_PER_BARBER", 1)
    await _join(session_factory, sample_barber, sample_clients[0], mock_notifier)
    async with session_factory() as s:
        o = await QueueService(s, notifier=mock_notifier).join_queue(
            sample_barber.id, sample_barber.services[0].id, None, walkin_name="Walk", pay_now=False, enforce_capacity=False)
        await s.commit()
        assert o.id


@pytest.mark.asyncio
async def test_M23_a_service_running_over_its_time_still_counts_in_the_wait(session_factory, sample_barber, sample_clients, mock_notifier):
    oid = await _join(session_factory, sample_barber, sample_clients[0], mock_notifier)
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        await qs.client_arrived(oid)
        await s.commit()
    async with session_factory() as s:
        o = await s.get(Order, oid)
        o.started_at = o.started_at - timedelta(minutes=o.duration_minutes + 20)  # 20 minutes over
        await s.commit()
    async with session_factory() as s:
        qs = QueueService(s)
        _, wait = await qs.get_barber_queue_metrics(sample_barber.id)
        assert wait > 0, "an overrunning service must not make the next client's wait zero"


def test_M24_estimated_start_is_now_plus_wait(monkeypatch):
    fake_now = datetime(2026, 10, 14, 10, 0, tzinfo=TASHKENT_TZ)
    monkeypatch.setattr("app.services.queue_service.now_tashkent", lambda: fake_now)
    assert QueueService.estimated_start_text(0) == "10:00"
    assert QueueService.estimated_start_text(95) == "11:35"


# ----------------------------------------------------------------------------- production configuration
def _prod(**over):
    kw = dict(
        _env_file=None, ENV="production", PAYMENTS_MODE="live", OWNER_TELEGRAM_IDS=[555111222],
        BOT_TOKEN="987654321:" + "AAH" + "x" * 35,
        WEBHOOK_SECRET="a" * 40, WEBHOOK_PATH_SECRET="b" * 40, CRON_SECRET="c" * 40,
        ENABLED_PAYMENT_METHODS=["CASH", "TRANSFER"],
        DATABASE_URL="postgresql+asyncpg://u:p@db:5432/x",
        PAYMENT_CARD_NUMBER="8600 1234 5678 9012", PAYMENT_CARD_HOLDER="ALI VALIYEV",
    )
    kw.update(over)
    return kw


def test_M30_production_accepts_a_real_card_and_rejects_placeholders():
    Settings(**_prod()).validate_runtime()
    for bad in (
        dict(PAYMENT_CARD_NUMBER=""),
        dict(PAYMENT_CARD_NUMBER="0000 0000 0000 0000"),
        dict(PAYMENT_CARD_NUMBER="8600 1234"),
        dict(PAYMENT_CARD_HOLDER=""),
        dict(PAYMENT_CARD_HOLDER="CHANGE_ME card holder name"),
    ):
        with pytest.raises(ValueError):
            Settings(**_prod(**bad)).validate_runtime()


def test_M31_card_is_not_required_when_transfer_is_not_enabled():
    Settings(**_prod(ENABLED_PAYMENT_METHODS=["CASH"], PAYMENT_CARD_NUMBER="", PAYMENT_CARD_HOLDER="")).validate_runtime()


def test_M32_payment_keyboard_follows_the_enabled_methods(monkeypatch):
    from app.keyboards.client import get_payment_methods_keyboard, get_payment_timing_keyboard

    def cbs(kb):
        return [b.callback_data for row in kb.inline_keyboard for b in row]

    monkeypatch.setattr(settings, "ENABLED_PAYMENT_METHODS", ["CASH", "TRANSFER"])
    assert {"pay_method:5:CASH", "pay_method:5:TRANSFER"} <= set(cbs(get_payment_methods_keyboard(5)))
    assert not any(c.startswith("pay_timing:now") for c in cbs(get_payment_timing_keyboard(1, 2)))  # no online provider: no "pay now"
    monkeypatch.setattr(settings, "ENABLED_PAYMENT_METHODS", ["CASH"])
    assert "pay_method:5:TRANSFER" not in cbs(get_payment_methods_keyboard(5))
    monkeypatch.setattr(settings, "ENABLED_PAYMENT_METHODS", ["CASH", "CLICK"])
    assert any(c.startswith("pay_timing:now") for c in cbs(get_payment_timing_keyboard(1, 2)))


@pytest.mark.asyncio
async def test_M40_unconfirmed_receipt_reminder_sent_after_timeout(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    from app.services.due_work_service import process_due_work
    from app.utils.time_utils import now_utc

    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    pid = await _submit(session_factory, oid, client, mock_notifier)

    # Set receipt_sent_at to 6 minutes ago
    async with session_factory() as s:
        p = await PaymentRepository(s).get_by_id(pid)
        p.receipt_sent_at = now_utc() - timedelta(minutes=6)
        await s.commit()

    mock_notifier.sent_events.clear()
    res = await process_due_work(session_factory, notifier=mock_notifier)
    assert res["reminders_sent"] >= 1
    events = [e for e in mock_notifier.sent_events if e.get("telegram_id") == STAFF_BARBER_TG]
    assert events
    last_event = events[-1]
    buttons = [b.callback_data for row in last_event["reply_markup"].inline_keyboard for b in row]
    assert f"tr_ok:{pid}" in buttons and f"tr_no:{pid}" in buttons


@pytest.mark.asyncio
async def test_M41_barber_pending_receipts_screen_lists_unconfirmed_receipts(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    from app.handlers import barber as barber_handlers

    client = sample_clients[0]
    oid = await _join(session_factory, sample_barber, client, mock_notifier)
    await _submit(session_factory, oid, client, mock_notifier)

    barber_user, _ = await _staff(session_factory, STAFF_BARBER_TG)
    call = _call("b_menu:pending_receipts", STAFF_BARBER_TG)

    async with session_factory() as s:
        await barber_handlers.handle_barber_pending_receipts(call, s, barber_user, "uz")

    assert call.message.answer_photo.await_count >= 1 or call.message.answer.await_count >= 1


@pytest.mark.asyncio
async def test_M42_client_menu_or_start_during_receipt_flow_clears_state(
    session_factory, sample_barber, sample_clients
):
    client = sample_clients[0]
    state = MagicMock()
    state.clear = AsyncMock()
    state.set_state = AsyncMock()

    msg = MagicMock()
    msg.text = "/start"
    msg.answer = AsyncMock()

    async with session_factory() as s:
        await client_handlers.handle_receipt_not_a_photo(msg, state, s, client, "uz")

    state.clear.assert_awaited()

