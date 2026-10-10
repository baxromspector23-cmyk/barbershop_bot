from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import Settings, settings
from app.handlers.barber import (
    handle_b_arrived,
    handle_b_cancel,
    handle_b_cash,
    handle_b_done,
    handle_b_no_show,
    handle_toggle_service,
)
from app.handlers.client import handle_pay_method_selected
from app.handlers.payments import handle_pre_checkout
from app.models.barber import Barber, BarberWorkingHours
from app.models.enums import Language, OrderStatus, PaymentMethod, PaymentStatus, UserRole
from app.models.order import Order
from app.models.payment import Payment
from app.models.service import Service
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.services.due_work_service import process_due_work
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueService
from app.utils.time_utils import now_utc


@pytest.fixture
async def second_barber(session_factory) -> Barber:
    async with session_factory() as session:
        barber_user = User(
            telegram_id=999999,
            username="barber_second",
            first_name="Second",
            last_name="Barber",
            language=Language.UZ.value,
            role=UserRole.BARBER.value,
        )
        session.add(barber_user)
        await session.flush()

        barber = Barber(
            user_id=barber_user.id,
            display_name="Second Barber",
            is_active=True,
            is_paused=False,
        )
        session.add(barber)
        await session.flush()

        for w in range(7):
            wh = BarberWorkingHours(
                barber_id=barber.id,
                weekday=w,
                start_time=time(0, 0),
                end_time=time(23, 59),
                is_day_off=False,
            )
            session.add(wh)

        svc = Service(
            barber_id=barber.id,
            name="Soch kesish (2)",
            price=40000,
            duration_minutes=25,
            is_active=True,
        )
        session.add(svc)
        await session.commit()

        stmt = (
            select(Barber)
            .where(Barber.id == barber.id)
            .options(
                selectinload(Barber.working_hours),
                selectinload(Barber.services),
                selectinload(Barber.user),
            )
        )
        res = await session.execute(stmt)
        return res.scalar_one()


# ---------------------------------------------------------------------------
# F1 (M1): Prepaid client asked to pay again
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f1_prepaid_client_no_repay(
    db_session, session_factory, sample_barber, sample_clients, mock_notifier
):
    """
    M1: After 'Xizmat ko'rsatildi', handle_b_done sends a pay-now keyboard
    even when order's payment is already PAID.
    Prepaid client should only receive thank-you/receipt message, NOT payment keyboard.
    Pay-after client must still receive payment keyboard.
    """
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]
    client = sample_clients[0]

    # Prepaid flow
    order = await qs.join_queue(sample_barber.id, service.id, client, pay_now=True)
    ps = PaymentService(db_session, notifier=mock_notifier)
    await ps.handle_successful_payment(
        method=PaymentMethod.CLICK.value,
        provider_payment_id="tx_prepaid_f1",
        amount=order.price,
        order_id=order.id,
    )
    await qs.client_arrived(order.id)
    await db_session.commit()

    bot = MagicMock()
    bot.send_message = AsyncMock()

    call = MagicMock()
    call.data = f"b_done:{order.id}"
    call.answer = AsyncMock()
    call.message = MagicMock()
    call.message.delete = AsyncMock()

    await handle_b_done(call, db_session, sample_barber.user, bot, "uz")

    # Client must NOT be sent the payment methods keyboard
    for call_args in bot.send_message.call_args_list:
        kwargs = call_args.kwargs
        reply_markup = kwargs.get("reply_markup")
        if reply_markup and hasattr(reply_markup, "inline_keyboard"):
            # Check if any button starts with pay_method
            has_pay_method = any(
                any(btn.callback_data and btn.callback_data.startswith("pay_method:") for btn in row)
                for row in reply_markup.inline_keyboard
            )
            assert not has_pay_method, "Prepaid client received pay_method keyboard!"


@pytest.mark.asyncio
async def test_f1_pay_after_client_gets_keyboard(
    db_session, sample_barber, sample_clients, mock_notifier
):
    """M1 acceptance: pay-after client still gets the payment keyboard."""
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]
    client = sample_clients[0]

    order = await qs.join_queue(sample_barber.id, service.id, client, pay_now=False)
    await qs.client_arrived(order.id)
    await db_session.commit()

    bot = MagicMock()
    bot.send_message = AsyncMock()

    call = MagicMock()
    call.data = f"b_done:{order.id}"
    call.answer = AsyncMock()
    call.message = MagicMock()
    call.message.delete = AsyncMock()

    await handle_b_done(call, db_session, sample_barber.user, bot, "uz")

    # Client MUST be sent the payment methods keyboard
    found_keyboard = False
    for call_args in bot.send_message.call_args_list:
        kwargs = call_args.kwargs
        reply_markup = kwargs.get("reply_markup")
        if reply_markup and hasattr(reply_markup, "inline_keyboard"):
            if any(
                any(btn.callback_data and btn.callback_data.startswith("pay_method:") for btn in row)
                for row in reply_markup.inline_keyboard
            ):
                found_keyboard = True
    assert found_keyboard, "Pay-after client must receive payment methods keyboard!"


# ---------------------------------------------------------------------------
# F2 (A1): Foreign barber cannot manage another barber's order (cash/cancel)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f2_foreign_barber_order_guard(
    db_session, sample_barber, second_barber, sample_clients, mock_notifier
):
    """
    A1: Acting user must be the order's own barber, or the owner.
    Barber B cannot confirm cash or cancel Barber A's order.
    """
    qs = QueueService(db_session, notifier=mock_notifier)
    svc = sample_barber.services[0]
    client = sample_clients[0]
    order = await qs.join_queue(sample_barber.id, svc.id, client, pay_now=False)
    await qs.client_arrived(order.id)
    await qs.complete_service(order.id)
    await db_session.commit()

    bot = MagicMock()
    call = MagicMock()
    call.data = f"b_cash:{order.id}"
    call.answer = AsyncMock()
    call.message = MagicMock()
    call.message.delete = AsyncMock()

    # Second barber tries to mark cash on sample_barber's order
    await handle_b_cash(call, db_session, second_barber.user, bot, "uz")

    # Must be answered with permission alert
    call.answer.assert_called_once()
    args, kwargs = call.answer.call_args
    assert kwargs.get("show_alert") is True
    # Order must NOT have a PAID cash payment
    pay_repo = PaymentRepository(db_session)
    payment = await pay_repo.get_by_order_id(order.id)
    assert payment is None or payment.status != PaymentStatus.PAID.value


# ---------------------------------------------------------------------------
# F3 (A2): Foreign barber cannot toggle another barber's service
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f3_foreign_barber_service_toggle_guard(
    db_session, sample_barber, second_barber
):
    """
    A2: Acting user must be the service's own barber, or the owner.
    Barber B cannot toggle Barber A's service.
    """
    svc = sample_barber.services[0]
    initial_active = svc.is_active

    call = MagicMock()
    call.data = f"b_svc_toggle:{svc.id}"
    call.answer = AsyncMock()
    call.message = MagicMock()
    call.message.edit_text = AsyncMock()

    await handle_toggle_service(call, db_session, second_barber.user, "uz")

    call.answer.assert_called()
    _, kwargs = call.answer.call_args
    assert kwargs.get("show_alert") is True

    # Service status must not change
    await db_session.refresh(svc)
    assert svc.is_active == initial_active


# ---------------------------------------------------------------------------
# F4 (M4): FAKE payment restricted and client order ownership validated
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f4_fake_payment_and_client_order_ownership(
    db_session, sample_barber, sample_clients, monkeypatch
):
    """
    M4: FAKE must exist only when PAYMENTS_MODE == 'test' and ENV != 'production'.
    Every client callback that carries order id must verify order belongs to acting user.
    """
    qs = QueueService(db_session)
    svc = sample_barber.services[0]
    client1 = sample_clients[0]
    client2 = sample_clients[1]

    order = await qs.join_queue(sample_barber.id, svc.id, client1, pay_now=True)
    await db_session.commit()

    bot = MagicMock()
    call = MagicMock()
    call.data = f"pay_method:{order.id}:FAKE"
    call.answer = AsyncMock()
    call.message = MagicMock()
    call.message.edit_text = AsyncMock()

    # 1. Foreign client trying to pay or interact with client1's order
    await handle_pay_method_selected(call, db_session, bot, client2, "uz")
    call.answer.assert_called()
    assert "not found" in call.answer.call_args[0][0].lower() or "permission" in call.answer.call_args[0][0].lower() or call.answer.call_args[1].get("show_alert") is True

    # 2. In production, FAKE payment must be forbidden even for rightful client
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "PAYMENTS_MODE", "live")
    call.answer.reset_mock()
    await handle_pay_method_selected(call, db_session, bot, client1, "uz")
    pay_repo = PaymentRepository(db_session)
    p = await pay_repo.get_by_order_id(order.id)
    assert p is None or p.status != PaymentStatus.PAID.value


# ---------------------------------------------------------------------------
# F5a (M3): Second payment creates separate row with REFUND_PENDING and DUPLICATE_CHARGE
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f5a_duplicate_payment_creates_refund_pending(
    db_session, sample_barber, sample_clients, mock_notifier
):
    """
    M3: A different charge id for an order that already has a PAID payment
    must be stored as its OWN row with status REFUND_PENDING and reason DUPLICATE_CHARGE.
    """
    qs = QueueService(db_session, notifier=mock_notifier)
    svc = sample_barber.services[0]
    client = sample_clients[0]
    order = await qs.join_queue(sample_barber.id, svc.id, client, pay_now=True)
    await db_session.commit()

    ps = PaymentService(db_session, notifier=mock_notifier)
    # First payment
    p1 = await ps.handle_successful_payment(
        method=PaymentMethod.CLICK.value,
        provider_payment_id="click_tx_first",
        amount=order.price,
        order_id=order.id,
    )
    await db_session.commit()
    assert p1.status == PaymentStatus.PAID.value

    # Second payment with different provider_payment_id arrives
    p2 = await ps.handle_successful_payment(
        method=PaymentMethod.PAYME.value,
        provider_payment_id="payme_tx_second",
        amount=order.price,
        order_id=order.id,
    )
    await db_session.commit()

    # Must be a separate row
    assert p2.id != p1.id
    assert p2.status == PaymentStatus.REFUND_PENDING.value
    assert getattr(p2, "refund_reason", None) == "DUPLICATE_CHARGE"

    # Primary payment via get_by_order_id must still be p1
    primary = await ps.payment_repo.get_by_order_id(order.id)
    assert primary.id == p1.id
    assert primary.status == PaymentStatus.PAID.value


@pytest.mark.asyncio
async def test_f5a_same_id_idempotency(
    db_session, sample_barber, sample_clients, mock_notifier
):
    """M3 acceptance: same-id arriving twice is idempotent."""
    qs = QueueService(db_session, notifier=mock_notifier)
    svc = sample_barber.services[0]
    client = sample_clients[0]
    order = await qs.join_queue(sample_barber.id, svc.id, client, pay_now=True)
    await db_session.commit()

    ps = PaymentService(db_session, notifier=mock_notifier)
    p1 = await ps.handle_successful_payment(
        method=PaymentMethod.CLICK.value,
        provider_payment_id="same_tx_123",
        amount=order.price,
        order_id=order.id,
    )
    await db_session.commit()

    p2 = await ps.handle_successful_payment(
        method=PaymentMethod.CLICK.value,
        provider_payment_id="same_tx_123",
        amount=order.price,
        order_id=order.id,
    )
    assert p1.id == p2.id


@pytest.mark.asyncio
async def test_f5a_duplicate_charge_not_counted_in_revenue_reports(
    db_session, sample_barber, sample_clients, mock_notifier
):
    """M3 acceptance: duplicate charge does not count toward revenue."""
    from app.services.report_service import ReportService

    qs = QueueService(db_session, notifier=mock_notifier)
    svc = sample_barber.services[0]
    client = sample_clients[0]
    order = await qs.join_queue(sample_barber.id, svc.id, client, pay_now=True)
    await db_session.commit()

    ps = PaymentService(db_session, notifier=mock_notifier)
    await ps.handle_successful_payment(
        method=PaymentMethod.CLICK.value,
        provider_payment_id="valid_tx_1",
        amount=order.price,
        order_id=order.id,
    )
    # Service performed and completed
    await qs.client_arrived(order.id)
    await qs.complete_service(order.id)

    # Duplicate second payment arrives
    await ps.handle_successful_payment(
        method=PaymentMethod.PAYME.value,
        provider_payment_id="duplicate_tx_2",
        amount=order.price,
        order_id=order.id,
    )
    await db_session.commit()

    rs = ReportService(db_session)
    report = await rs.generate_report(period_type="today", offset=0)
    # Revenue must equal order.price, NOT 2 * order.price
    assert report.total_revenue == order.price


@pytest.mark.asyncio
async def test_f5a_payment_on_dead_order(
    db_session, sample_barber, sample_clients, mock_notifier
):
    """M3 acceptance: payment on dead order recorded as REFUND_PENDING, order not activated."""
    qs = QueueService(db_session, notifier=mock_notifier)
    svc = sample_barber.services[0]
    client = sample_clients[0]
    order = await qs.join_queue(sample_barber.id, svc.id, client, pay_now=False)
    await qs.cancel_by_client(order.id, client.id)
    await db_session.commit()

    ps = PaymentService(db_session, notifier=mock_notifier)
    payment = await ps.handle_successful_payment(
        method=PaymentMethod.CLICK.value,
        provider_payment_id="dead_order_tx",
        amount=order.price,
        order_id=order.id,
    )
    await db_session.commit()

    assert payment.status == PaymentStatus.REFUND_PENDING.value
    # Order must remain cancelled
    await db_session.refresh(order)
    assert order.status == OrderStatus.CANCELLED_BY_CLIENT.value


# ---------------------------------------------------------------------------
# F5b (M2): handle_pre_checkout strict validation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f5b_pre_checkout_strict_validation(
    db_session, sample_barber, sample_clients, mock_notifier
):
    """
    M2: handle_pre_checkout must answer ok=False when currency is not UZS,
    or payer is not the order's client, or order already has a PAID payment.
    """
    qs = QueueService(db_session, notifier=mock_notifier)
    svc = sample_barber.services[0]
    client = sample_clients[0]
    order = await qs.join_queue(sample_barber.id, svc.id, client, pay_now=True)
    await db_session.commit()

    query = MagicMock()
    query.invoice_payload = f"order_{order.id}_CLICK"
    query.total_amount = order.price * 100
    query.currency = "USD"  # Non-UZS currency
    query.from_user.id = client.telegram_id
    query.answer = AsyncMock()

    await handle_pre_checkout(query, db_session)
    query.answer.assert_called_with(ok=False, error_message="Valyuta faqat UZS bo'lishi kerak.")


@pytest.mark.asyncio
async def test_f5b_pre_checkout_reject_reasons_and_accept(
    db_session, sample_barber, sample_clients, mock_notifier
):
    """M2 acceptance: one test per reject reason and one for the accept case."""
    qs = QueueService(db_session, notifier=mock_notifier)
    svc = sample_barber.services[0]
    client = sample_clients[0]
    other_client = sample_clients[1]

    order = await qs.join_queue(sample_barber.id, svc.id, client, pay_now=False)
    await qs.client_arrived(order.id)
    await qs.complete_service(order.id)
    await db_session.commit()

    # 1. Accept case: pay-after client paying after service
    q_accept = MagicMock()
    q_accept.invoice_payload = f"order_{order.id}_CLICK"
    q_accept.total_amount = order.price * 100
    q_accept.currency = "UZS"
    q_accept.from_user.id = client.telegram_id
    q_accept.answer = AsyncMock()
    await handle_pre_checkout(q_accept, db_session)
    q_accept.answer.assert_called_with(ok=True)

    # 2. Reject: foreign payer
    q_foreign = MagicMock()
    q_foreign.invoice_payload = f"order_{order.id}_CLICK"
    q_foreign.total_amount = order.price * 100
    q_foreign.currency = "UZS"
    q_foreign.from_user.id = other_client.telegram_id
    q_foreign.answer = AsyncMock()
    await handle_pre_checkout(q_foreign, db_session)
    assert q_foreign.answer.call_args.kwargs.get("ok") is False

    # 3. Reject: malformed payload
    q_malformed = MagicMock()
    q_malformed.invoice_payload = "invalid_payload"
    q_malformed.total_amount = order.price * 100
    q_malformed.currency = "UZS"
    q_malformed.from_user.id = client.telegram_id
    q_malformed.answer = AsyncMock()
    await handle_pre_checkout(q_malformed, db_session)
    assert q_malformed.answer.call_args.kwargs.get("ok") is False

    # 4. Reject: order not found
    q_not_found = MagicMock()
    q_not_found.invoice_payload = "order_999999_CLICK"
    q_not_found.total_amount = order.price * 100
    q_not_found.currency = "UZS"
    q_not_found.from_user.id = client.telegram_id
    q_not_found.answer = AsyncMock()
    await handle_pre_checkout(q_not_found, db_session)
    assert q_not_found.answer.call_args.kwargs.get("ok") is False

    # 5. Reject: amount mismatch
    q_amount = MagicMock()
    q_amount.invoice_payload = f"order_{order.id}_CLICK"
    q_amount.total_amount = 1000  # wrong amount
    q_amount.currency = "UZS"
    q_amount.from_user.id = client.telegram_id
    q_amount.answer = AsyncMock()
    await handle_pre_checkout(q_amount, db_session)
    assert q_amount.answer.call_args.kwargs.get("ok") is False

    # 6. Reject: order already PAID
    ps = PaymentService(db_session, notifier=mock_notifier)
    await ps.handle_successful_payment(
        method=PaymentMethod.CLICK.value,
        provider_payment_id="tx_test_already_paid",
        amount=order.price,
        order_id=order.id,
    )
    await db_session.commit()

    q_already_paid = MagicMock()
    q_already_paid.invoice_payload = f"order_{order.id}_CLICK"
    q_already_paid.total_amount = order.price * 100
    q_already_paid.currency = "UZS"
    q_already_paid.from_user.id = client.telegram_id
    q_already_paid.answer = AsyncMock()
    await handle_pre_checkout(q_already_paid, db_session)
    assert q_already_paid.answer.call_args.kwargs.get("ok") is False

    # 7. Reject: cancelled order
    order2 = await qs.join_queue(sample_barber.id, svc.id, other_client, pay_now=False)
    await qs.cancel_by_client(order2.id, other_client.id)
    await db_session.commit()

    q_cancelled = MagicMock()
    q_cancelled.invoice_payload = f"order_{order2.id}_CLICK"
    q_cancelled.total_amount = order2.price * 100
    q_cancelled.currency = "UZS"
    q_cancelled.from_user.id = other_client.telegram_id
    q_cancelled.answer = AsyncMock()
    await handle_pre_checkout(q_cancelled, db_session)
    assert q_cancelled.answer.call_args.kwargs.get("ok") is False


# ---------------------------------------------------------------------------
# F6 (D2): Owner alert spam prevented with persisted marker stale_alerted_at
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f6_owner_alert_spam_prevented(
    session_factory, sample_barber, sample_clients, mock_notifier, monkeypatch
):
    """
    D2: process_due_work runs every 15s. An unclosed IN_SERVICE order from a previous day
    must alert the owner once, setting stale_alerted_at. Second run must NOT re-alert.
    """
    monkeypatch.setattr(settings, "OWNER_TELEGRAM_IDS", [111111])

    async with session_factory() as session:
        qs = QueueService(session, notifier=mock_notifier)
        svc = sample_barber.services[0]
        order = await qs.join_queue(sample_barber.id, svc.id, sample_clients[0], pay_now=False)
        await qs.client_arrived(order.id)
        # Set ticket_date to yesterday
        order.ticket_date = date.today() - timedelta(days=1)
        await session.commit()
        order_id = order.id

    mock_notifier.sent_events.clear()

    # Tick 1
    await process_due_work(session_factory, notifier=mock_notifier)
    alert_count_1 = len([e for e in mock_notifier.sent_events if "IN_SERVICE" in e["text"]])
    assert alert_count_1 == 1

    # Tick 2 immediately after
    await process_due_work(session_factory, notifier=mock_notifier)
    alert_count_2 = len([e for e in mock_notifier.sent_events if "IN_SERVICE" in e["text"]])
    # Must NOT have sent a duplicate alert!
    assert alert_count_2 == 1

    # Verify stale_alerted_at is set on the order
    async with session_factory() as session:
        repo = OrderRepository(session)
        o = await repo.get_by_id(order_id)
        assert getattr(o, "stale_alerted_at", None) is not None


# ---------------------------------------------------------------------------
# F7 (M5): Refunds flagged at end-of-day expiry and cancellations
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f7_cancellation_paid_order_refund_pending(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    """
    M5: EOD expiry of an order that has a PAID payment must mark payment as REFUND_PENDING,
    notify the owner, and notify the client.
    """
    async with session_factory() as session:
        qs = QueueService(session, notifier=mock_notifier)
        svc = sample_barber.services[0]
        client = sample_clients[0]
        order = await qs.join_queue(sample_barber.id, svc.id, client, pay_now=True)
        ps = PaymentService(session, notifier=mock_notifier)
        await ps.handle_successful_payment(
            method=PaymentMethod.CLICK.value,
            provider_payment_id="tx_paid_eod",
            amount=order.price,
            order_id=order.id,
        )
        order.ticket_date = date.today() - timedelta(days=1)
        await session.commit()
        order_id = order.id

    await process_due_work(session_factory, notifier=mock_notifier)

    async with session_factory() as session:
        pay_repo = PaymentRepository(session)
        payment = await pay_repo.get_by_order_id(order_id)
        assert payment.status == PaymentStatus.REFUND_PENDING.value


# ---------------------------------------------------------------------------
# F8 (C1): validate_runtime production checks listing all violations
# ---------------------------------------------------------------------------
def test_f8_validate_runtime_production_checks():
    """
    C1: validate_runtime() must raise listing ALL problems at once in production:
    default OWNER_TELEGRAM_IDS, short secrets, non-Postgres DATABASE_URL, FAKE enabled, PAYNET_ENABLED.
    """
    s = Settings(
        BOT_TOKEN="invalid_token",
        ENV="production",
        PAYMENTS_MODE="live",
        DATABASE_URL="sqlite+aiosqlite:///test.db",
        OWNER_TELEGRAM_IDS=[123456789],
        WEBHOOK_SECRET="short",
        WEBHOOK_PATH_SECRET="short",
        CRON_SECRET="short",
        ENABLED_PAYMENT_METHODS=["CLICK", "PAYME", "FAKE"],
        PAYNET_ENABLED=True,
    )

    with pytest.raises(ValueError) as exc_info:
        s.validate_runtime()

    err = str(exc_info.value)
    assert "OWNER_TELEGRAM_IDS" in err
    assert "CRON_SECRET" in err or "WEBHOOK_SECRET" in err
    assert "DATABASE_URL" in err
    assert "FAKE" in err
    assert "PAYNET" in err


# ---------------------------------------------------------------------------
# F9 (A3): Barber callbacks authorization helper
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f9_barber_callback_authorization(
    db_session, sample_barber, second_barber, sample_clients, mock_notifier
):
    """
    A3: Foreign barber attempting b_arrived or b_cancel on Barber A's order
    must be rejected and DB must not be modified.
    """
    qs = QueueService(db_session, notifier=mock_notifier)
    svc = sample_barber.services[0]
    client = sample_clients[0]
    order = await qs.join_queue(sample_barber.id, svc.id, client, pay_now=False)
    await db_session.commit()

    bot = MagicMock()
    call = MagicMock()
    call.data = f"b_arrived:{order.id}"
    call.answer = AsyncMock()
    call.message = MagicMock()
    call.message.edit_reply_markup = AsyncMock()

    await handle_b_arrived(call, db_session, second_barber.user, bot, "uz")

    call.answer.assert_called()
    _, kwargs = call.answer.call_args
    assert kwargs.get("show_alert") is True

    # Order status must still be CALLED, not IN_SERVICE
    await db_session.refresh(order)
    assert order.status == OrderStatus.CALLED.value


# ---------------------------------------------------------------------------
# F10a (D1): Naive vs aware datetimes under SQLite in get_barber_queue_metrics
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f10a_naive_vs_aware_datetime_sqlite(
    db_session, sample_barber, sample_clients, mock_notifier
):
    """
    D1: Under SQLite, datetime columns must return timezone-aware UTC.
    get_barber_queue_metrics with an IN_SERVICE order must not raise TypeError.
    """
    qs = QueueService(db_session, notifier=mock_notifier)
    svc = sample_barber.services[0]
    order = await qs.join_queue(sample_barber.id, svc.id, sample_clients[0], pay_now=False)
    await qs.client_arrived(order.id)
    await db_session.commit()
    db_session.expire_all()

    # Re-fetch from DB
    order_from_db = await qs.order_repo.get_by_id(order.id)
    # This calls now - o.started_at, which raises TypeError if started_at is naive
    queue_len, est_wait = await qs.get_barber_queue_metrics(sample_barber.id)
    assert order_from_db.started_at.tzinfo is not None, "started_at must be timezone-aware UTC"


# ---------------------------------------------------------------------------
# F10b (D1): In-service datetime arithmetic in due_work_service
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f10b_in_service_datetime_arithmetic(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    """
    D1: due_work_service candidate reminders does `current_utc >= due_time`
    where `due_time = o.started_at + timedelta(...)`. Must not raise TypeError under SQLite.
    """
    async with session_factory() as session:
        qs = QueueService(session, notifier=mock_notifier)
        svc = sample_barber.services[0]
        order = await qs.join_queue(sample_barber.id, svc.id, sample_clients[0], pay_now=False)
        await qs.client_arrived(order.id)
        await session.commit()

    # Run process_due_work without TypeError
    results = await process_due_work(session_factory, notifier=mock_notifier)
    assert isinstance(results, dict)
