from __future__ import annotations

import pytest

from app.models.enums import OrderStatus
from app.services.queue_service import QueueService


@pytest.mark.asyncio
async def test_lateness_first_move_back(db_session, sample_barber, sample_clients, mock_notifier):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]

    # Client 0 joins (CALLED)
    o1 = await qs.join_queue(sample_barber.id, service.id, sample_clients[0])
    # Client 1 joins (WAITING)
    o2 = await qs.join_queue(sample_barber.id, service.id, sample_clients[1])
    # Client 2 joins (WAITING)
    o3 = await qs.join_queue(sample_barber.id, service.id, sample_clients[2])
    await db_session.commit()

    pos_key_o1_before = o1.position_key
    pos_key_o2_before = o2.position_key

    # 1st lateness for o1
    await qs.handle_lateness(o1.id)
    await db_session.commit()

    reloaded_o1 = await qs.order_repo.get_by_id(o1.id)
    reloaded_o2 = await qs.order_repo.get_by_id(o2.id)
    reloaded_o3 = await qs.order_repo.get_by_id(o3.id)

    assert reloaded_o1.late_count == 1
    assert reloaded_o1.status == OrderStatus.WAITING.value
    # Order 1 and Order 2 swapped keys
    assert reloaded_o1.position_key == pos_key_o2_before
    assert reloaded_o2.position_key == pos_key_o1_before

    # Order 2 was promoted to CALLED
    assert reloaded_o2.status == OrderStatus.CALLED.value
    # Order 3 remains untouched
    assert reloaded_o3.status == OrderStatus.WAITING.value

    # Check notification for moved back
    moved_events = [
        e for e in mock_notifier.sent_events
        if e["telegram_id"] == sample_clients[0].telegram_id and "orqaga surildi" in e["text"]
    ]
    assert len(moved_events) >= 1


@pytest.mark.asyncio
async def test_lateness_when_nobody_behind(db_session, sample_barber, sample_clients, mock_notifier):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]

    # Only 1 client in queue
    o1 = await qs.join_queue(sample_barber.id, service.id, sample_clients[0])
    await db_session.commit()

    initial_deadline = o1.deadline_at

    # Lateness triggered
    await qs.handle_lateness(o1.id)
    await db_session.commit()

    reloaded_o1 = await qs.order_repo.get_by_id(o1.id)
    assert reloaded_o1.late_count == 1
    # Remains CALLED
    assert reloaded_o1.status == OrderStatus.CALLED.value
    # Has a new fresh deadline
    assert reloaded_o1.deadline_at >= initial_deadline


@pytest.mark.asyncio
async def test_third_lateness_cancels_no_show(db_session, sample_barber, sample_clients, mock_notifier):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]

    o1 = await qs.join_queue(sample_barber.id, service.id, sample_clients[0])
    o2 = await qs.join_queue(sample_barber.id, service.id, sample_clients[1])
    await db_session.commit()

    # 1st lateness (o1 moves back, o2 becomes CALLED)
    await qs.handle_lateness(o1.id)
    await db_session.commit()

    # Finish o2
    await qs.client_arrived(o2.id)
    await qs.complete_service(o2.id)
    await db_session.commit()

    # o1 is now CALLED again
    reloaded_o1 = await qs.order_repo.get_by_id(o1.id)
    assert reloaded_o1.status == OrderStatus.CALLED.value

    # 2nd lateness for o1
    await qs.handle_lateness(o1.id)
    await db_session.commit()
    reloaded_o1 = await qs.order_repo.get_by_id(o1.id)
    assert reloaded_o1.late_count == 2
    assert reloaded_o1.status == OrderStatus.CALLED.value

    # 3rd lateness for o1 -> CANCELLED_NO_SHOW
    await qs.handle_lateness(o1.id)
    await db_session.commit()
    reloaded_o1 = await qs.order_repo.get_by_id(o1.id)
    assert reloaded_o1.late_count == 3
    assert reloaded_o1.status == OrderStatus.CANCELLED_NO_SHOW.value

    # Verify no-show notification
    no_show_events = [
        e for e in mock_notifier.sent_events
        if e["telegram_id"] == sample_clients[0].telegram_id and "3 marta kelmadingiz" in e["text"]
    ]
    assert len(no_show_events) == 1
