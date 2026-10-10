from __future__ import annotations

import asyncio

import pytest

from app.models.enums import OrderStatus
from app.services.queue_service import QueueService


@pytest.mark.asyncio
async def test_concurrent_joins_preserve_ordering(session_factory, sample_barber, sample_clients, mock_notifier):
    # Simulate 2 clients attempting to join the queue concurrently
    service = sample_barber.services[0]
    client1 = sample_clients[0]
    client2 = sample_clients[1]

    async def join_client(client):
        async with session_factory() as session:
            qs = QueueService(session, notifier=mock_notifier)
            order = await qs.join_queue(
                barber_id=sample_barber.id,
                service_id=service.id,
                client=client,
            )
            await session.commit()
            return order.id, order.position_key, order.ticket_no

    results = await asyncio.gather(join_client(client1), join_client(client2))

    pos_keys = [r[1] for r in results]
    tickets = [r[2] for r in results]

    # Verify monotonic, unique position keys and tickets
    assert len(set(pos_keys)) == 2
    assert len(set(tickets)) == 2
    assert set(tickets) == {1, 2}
    assert set(pos_keys) == {1, 2}

    # Verify queue state in DB
    async with session_factory() as session:
        qs = QueueService(session)
        active = await qs.order_repo.get_active_orders_for_barber(sample_barber.id)
        assert len(active) == 2
        # First order must be CALLED, second must be WAITING
        assert active[0].status == OrderStatus.CALLED.value
        assert active[1].status == OrderStatus.WAITING.value
