from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.enums import PaymentStatus
from app.models.payment import Payment
from app.services.payment_service import PaymentService
from app.services.queue_service import QueueService


@pytest.mark.asyncio
async def test_amount_mismatch_creates_refund_and_notifies_owner(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0], pay_now=True)
        await s.commit()
        order_id, price = o.id, o.price

    mock_notifier.send_message = AsyncMock()

    async with session_factory() as s:
        ps = PaymentService(s, notifier=mock_notifier)
        wrong_amount = price + 10000
        payment = await ps.handle_successful_payment("CLICK", "tx_wrong", wrong_amount, order_id)
        await s.commit()

        assert payment.status == PaymentStatus.REFUND_PENDING.value
        assert payment.refund_reason == "AMOUNT_MISMATCH"

    # Verify owner notification was sent
    assert mock_notifier.send_message.called
    calls = [c for c in mock_notifier.send_message.call_args_list if "noto'g'ri summa" in c.args[1] or "Неверная сумма" in c.args[1]]
    assert len(calls) > 0


@pytest.mark.asyncio
async def test_critical_failure_notifies_owner(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0], pay_now=True)
        await s.commit()
        order_id, price = o.id, o.price

    mock_notifier.send_message = AsyncMock()

    async with session_factory() as s:
        ps = PaymentService(s, notifier=mock_notifier)
        with patch.object(ps, "_execute_successful_payment", side_effect=RuntimeError("Simulated database failure")):
            with pytest.raises(RuntimeError):
                await ps.handle_successful_payment("CLICK", "tx_fail", price, order_id)

    # Verify owner notification was sent for critical failure
    assert mock_notifier.send_message.called
    calls = [c for c in mock_notifier.send_message.call_args_list if "DIQQAT" in c.args[1] or "ВНИМАНИЕ" in c.args[1]]
    assert len(calls) > 0


@pytest.mark.asyncio
async def test_critical_failure_with_database_error_and_rollback(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    from sqlalchemy import text

    async with session_factory() as s:
        qs = QueueService(s, notifier=mock_notifier)
        o = await qs.join_queue(sample_barber.id, sample_barber.services[0].id, sample_clients[0], pay_now=True)
        await s.commit()
        order_id, price = o.id, o.price

    mock_notifier.send_message = AsyncMock()

    async def db_boom(self, **kwargs):
        # Execute an invalid query to trigger database error
        await self.session.execute(text("SELECT 1 FROM nonexistent_table_test_boom"))

    with patch.object(PaymentService, "_execute_successful_payment", db_boom):
        async with session_factory() as s:
            ps = PaymentService(s, notifier=mock_notifier)
            with pytest.raises(Exception):
                await ps.handle_successful_payment("PAYME", "tx_boom_123", price, order_id)

    # Verify owner notification was dispatched with charge id and order id
    assert mock_notifier.send_message.called
    calls = [c for c in mock_notifier.send_message.call_args_list if "tx_boom_123" in c.args[1] and str(order_id) in c.args[1]]
    assert len(calls) > 0
