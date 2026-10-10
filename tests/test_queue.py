from __future__ import annotations

import pytest

from app.models.enums import OrderStatus
from app.services.queue_service import AlreadyInQueueError, QueueService


@pytest.mark.asyncio
async def test_empty_queue_join_calls_immediately(db_session, sample_barber, sample_clients, mock_notifier):
    qs = QueueService(db_session, notifier=mock_notifier)
    client1 = sample_clients[0]
    service = sample_barber.services[0]

    order = await qs.join_queue(
        barber_id=sample_barber.id,
        service_id=service.id,
        client=client1,
    )
    await db_session.commit()

    assert order.status == OrderStatus.CALLED.value
    assert order.ticket_no == 1
    assert order.position_key == 1
    assert order.deadline_at is not None

    # Verify notification was sent to client
    called_events = [e for e in mock_notifier.sent_events if e["telegram_id"] == client1.telegram_id]
    assert len(called_events) == 1
    assert "Navbatingiz keldi" in called_events[0]["text"]


@pytest.mark.asyncio
async def test_subsequent_joins_and_heads_up(db_session, sample_barber, sample_clients, mock_notifier):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]

    # Client 1 joins -> CALLED
    o1 = await qs.join_queue(sample_barber.id, service.id, sample_clients[0])
    # Client 2 joins -> WAITING, ahead=1 -> heads_up sent!
    o2 = await qs.join_queue(sample_barber.id, service.id, sample_clients[1])
    # Client 3 joins -> WAITING, ahead=2 -> heads_up NOT sent
    o3 = await qs.join_queue(sample_barber.id, service.id, sample_clients[2])
    await db_session.commit()

    assert o1.status == OrderStatus.CALLED.value
    assert o2.status == OrderStatus.WAITING.value
    assert o3.status == OrderStatus.WAITING.value

    assert o2.heads_up_sent is True
    assert o3.heads_up_sent is False

    # Check heads-up received by client 2
    heads_up_events = [
        e for e in mock_notifier.sent_events
        if e["telegram_id"] == sample_clients[1].telegram_id and "yo'lga chiqing" in e["text"]
    ]
    assert len(heads_up_events) == 1


@pytest.mark.asyncio
async def test_queue_position_and_wait_estimate(db_session, sample_barber, sample_clients, mock_notifier):
    qs = QueueService(db_session, notifier=mock_notifier)
    # Service 1: 30 mins
    svc30 = sample_barber.services[0]
    # Service 2: 20 mins
    svc20 = sample_barber.services[1]

    await qs.join_queue(sample_barber.id, svc30.id, sample_clients[0])  # CALLED (30m)
    o2 = await qs.join_queue(sample_barber.id, svc20.id, sample_clients[1])  # WAITING (20m)
    o3 = await qs.join_queue(sample_barber.id, svc30.id, sample_clients[2])  # WAITING (30m)
    await db_session.commit()

    active_orders = await qs.order_repo.get_active_orders_for_barber(sample_barber.id)
    assert len(active_orders) == 3

    # For order 2: 1 person ahead (order 1 = 30m), pos = 2
    pos2, ahead2, wait2 = qs.calculate_order_position_and_wait(o2, active_orders)
    assert pos2 == 2
    assert ahead2 == 1
    assert wait2 == 30

    # For order 3: 2 persons ahead (order 1 + order 2 = 50m), pos = 3
    pos3, ahead3, wait3 = qs.calculate_order_position_and_wait(o3, active_orders)
    assert pos3 == 3
    assert ahead3 == 2
    assert wait3 == 50


@pytest.mark.asyncio
async def test_call_next_after_completion(db_session, sample_barber, sample_clients, mock_notifier):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]

    o1 = await qs.join_queue(sample_barber.id, service.id, sample_clients[0])
    o2 = await qs.join_queue(sample_barber.id, service.id, sample_clients[1])
    await db_session.commit()

    assert o1.status == OrderStatus.CALLED.value
    assert o2.status == OrderStatus.WAITING.value

    # Barber starts service
    await qs.client_arrived(o1.id)
    await db_session.commit()
    assert o1.status == OrderStatus.IN_SERVICE.value

    # Barber completes service
    await qs.complete_service(o1.id)
    await db_session.commit()

    assert o1.status == OrderStatus.COMPLETED.value
    # Order 2 should now be CALLED!
    reloaded_o2 = await qs.order_repo.get_by_id(o2.id)
    assert reloaded_o2.status == OrderStatus.CALLED.value


@pytest.mark.asyncio
async def test_client_cannot_join_twice(db_session, sample_barber, sample_clients, mock_notifier):
    qs = QueueService(db_session, notifier=mock_notifier)
    service = sample_barber.services[0]
    client = sample_clients[0]

    await qs.join_queue(sample_barber.id, service.id, client)
    await db_session.commit()

    with pytest.raises(AlreadyInQueueError):
        await qs.join_queue(sample_barber.id, service.id, client)
