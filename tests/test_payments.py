from __future__ import annotations

import pytest

from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.services.payment_service import AmountMismatchError, PaymentService
from app.services.queue_service import QueueService


@pytest.mark.asyncio
async def test_prepaid_flow_activates_queue_after_payment(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]
    client = sample_clients[0]

    # Client chooses pay_now = True
    order = await qs.join_queue(sample_barber.id, service.id, client, pay_now=True)
    await db_session.commit()

    assert order.status == OrderStatus.PENDING_PAYMENT.value
    # Order is not in active queue yet
    active_orders = await qs.order_repo.get_active_orders_for_barber(sample_barber.id)
    assert len(active_orders) == 0

    # Process payment
    ps = PaymentService(db_session, notifier=mock_notifier)
    payment = await ps.handle_successful_payment(
        method=PaymentMethod.CLICK.value,
        provider_payment_id="click_tx_12345",
        amount=order.price,
        order_id=order.id,
    )
    await db_session.commit()

    assert payment.status == PaymentStatus.PAID.value
    # Order is now in active queue and CALLED (since barber was free)
    reloaded_order = await qs.order_repo.get_by_id(order.id)
    assert reloaded_order.status == OrderStatus.CALLED.value


@pytest.mark.asyncio
async def test_duplicate_payment_is_idempotent(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]
    client = sample_clients[0]

    order = await qs.join_queue(sample_barber.id, service.id, client, pay_now=True)
    await db_session.commit()

    ps = PaymentService(db_session, notifier=mock_notifier)
    # First confirmation
    p1 = await ps.handle_successful_payment(
        method=PaymentMethod.PAYME.value,
        provider_payment_id="payme_tx_999",
        amount=order.price,
        order_id=order.id,
    )
    await db_session.commit()

    event_count_before = len(mock_notifier.sent_events)

    # Second confirmation with same provider_payment_id
    p2 = await ps.handle_successful_payment(
        method=PaymentMethod.PAYME.value,
        provider_payment_id="payme_tx_999",
        amount=order.price,
        order_id=order.id,
    )
    await db_session.commit()

    assert p1.id == p2.id
    # No duplicate notifications sent
    assert len(mock_notifier.sent_events) == event_count_before


@pytest.mark.asyncio
async def test_cash_payment_confirmation(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]
    client = sample_clients[0]

    order = await qs.join_queue(sample_barber.id, service.id, client, pay_now=False)
    await qs.client_arrived(order.id)
    await qs.complete_service(order.id)
    await db_session.commit()

    ps = PaymentService(db_session, notifier=mock_notifier)
    payment = await ps.confirm_cash_payment(order.id, sample_barber.user_id)
    await db_session.commit()

    assert payment.status == PaymentStatus.PAID.value
    assert payment.method == PaymentMethod.CASH.value
    assert payment.amount == order.price


@pytest.mark.asyncio
async def test_cancelled_prepaid_order_flags_refund_pending(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]
    client = sample_clients[0]

    order = await qs.join_queue(sample_barber.id, service.id, client, pay_now=True)
    ps = PaymentService(db_session, notifier=mock_notifier)
    payment = await ps.handle_successful_payment(
        method=PaymentMethod.CLICK.value,
        provider_payment_id="tx_refund_test",
        amount=order.price,
        order_id=order.id,
    )
    await db_session.commit()

    # Client cancels prepaid order
    await qs.cancel_by_client(order.id, client.id)
    await db_session.commit()

    reloaded_payment = await ps.payment_repo.get_by_id(payment.id)
    assert reloaded_payment.status == PaymentStatus.REFUND_PENDING.value

    # Owner refunds manually
    await ps.mark_refund_done(reloaded_payment.id, sample_barber.user_id)
    await db_session.commit()

    assert reloaded_payment.status == PaymentStatus.REFUNDED.value


@pytest.mark.asyncio
async def test_payment_amount_mismatch_rejected(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]
    order = await qs.join_queue(sample_barber.id, service.id, sample_clients[0], pay_now=True)
    await db_session.commit()

    ps = PaymentService(db_session, notifier=mock_notifier)
    # Under N1: Never lose money. If amount mismatches, record payment as REFUND_PENDING with AMOUNT_MISMATCH
    payment = await ps.handle_successful_payment(
        method=PaymentMethod.CLICK.value,
        provider_payment_id="mismatch_tx",
        amount=10000,
        order_id=order.id,
    )
    assert payment.status == PaymentStatus.REFUND_PENDING.value
    assert payment.refund_reason == "AMOUNT_MISMATCH"
