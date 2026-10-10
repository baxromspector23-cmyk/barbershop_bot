from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.enums import OrderStatus
from app.services.due_work_service import process_due_work
from app.services.queue_service import QueueService
from app.utils.time_utils import now_utc


@pytest.mark.asyncio
async def test_due_work_processes_overdue_and_is_idempotent(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    # Setup initial orders
    async with session_factory() as session:
        qs = QueueService(session, notifier=mock_notifier)
        service = sample_barber.services[0]
        o1 = await qs.join_queue(sample_barber.id, service.id, sample_clients[0])
        o2 = await qs.join_queue(sample_barber.id, service.id, sample_clients[1])
        await session.commit()

        # Simulate deadline passing: set deadline_at to 5 minutes ago
        o1.deadline_at = now_utc() - timedelta(minutes=5)
        await session.commit()
        order1_id = o1.id
        order2_id = o2.id

    # 1st run of process_due_work
    res1 = await process_due_work(session_factory, notifier=mock_notifier)
    assert res1["lateness_processed"] == 1

    async with session_factory() as session:
        qs = QueueService(session)
        reloaded_o1 = await qs.order_repo.get_by_id(order1_id)
        reloaded_o2 = await qs.order_repo.get_by_id(order2_id)
        assert reloaded_o1.late_count == 1
        assert reloaded_o1.status == OrderStatus.WAITING.value
        assert reloaded_o2.status == OrderStatus.CALLED.value

    # 2nd run immediately: nothing is due, lateness_processed == 0 (Idempotent!)
    res2 = await process_due_work(session_factory, notifier=mock_notifier)
    assert res2["lateness_processed"] == 0


@pytest.mark.asyncio
async def test_due_work_with_delayed_tick(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    # Simulate a tick arriving 60 seconds (or 10 minutes) late
    async with session_factory() as session:
        qs = QueueService(session, notifier=mock_notifier)
        service = sample_barber.services[0]
        o1 = await qs.join_queue(sample_barber.id, service.id, sample_clients[0])
        await session.commit()

        # Overdue by 60 seconds
        o1.deadline_at = now_utc() - timedelta(seconds=60)
        await session.commit()
        order_id = o1.id

    res = await process_due_work(session_factory, notifier=mock_notifier)
    assert res["lateness_processed"] == 1

    async with session_factory() as session:
        qs = QueueService(session)
        reloaded_o1 = await qs.order_repo.get_by_id(order_id)
        assert reloaded_o1.late_count == 1
        # No one behind, so client was re-called
        assert reloaded_o1.status == OrderStatus.CALLED.value


@pytest.mark.asyncio
async def test_due_work_expires_old_pending_payments(
    session_factory, sample_barber, sample_clients, mock_notifier
):
    async with session_factory() as session:
        qs = QueueService(session, notifier=mock_notifier)
        service = sample_barber.services[0]
        # pay_now = True -> status = PENDING_PAYMENT
        o = await qs.join_queue(sample_barber.id, service.id, sample_clients[0], pay_now=True)
        await session.commit()

        # Simulate creation 15 minutes ago
        o.created_at = now_utc() - timedelta(minutes=15)
        await session.commit()
        order_id = o.id

    res = await process_due_work(session_factory, notifier=mock_notifier)
    assert res["pending_expired"] == 1

    async with session_factory() as session:
        qs = QueueService(session)
        reloaded = await qs.order_repo.get_by_id(order_id)
        assert reloaded.status == OrderStatus.EXPIRED.value
