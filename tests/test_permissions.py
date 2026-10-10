from __future__ import annotations

import pytest

from app.handlers.barber import is_staff
from app.handlers.owner import is_owner
from app.models.enums import UserRole
from app.models.user import User
from app.services.queue_service import QueueException, QueueService


def test_permission_helpers():
    owner = User(telegram_id=1, first_name="Owner", role=UserRole.OWNER.value)
    barber = User(telegram_id=2, first_name="Barber", role=UserRole.BARBER.value)
    client = User(telegram_id=3, first_name="Client", role=UserRole.CLIENT.value)

    assert is_owner(owner) is True
    assert is_owner(barber) is False
    assert is_owner(client) is False

    assert is_staff(owner) is True
    assert is_staff(barber) is True
    assert is_staff(client) is False


@pytest.mark.asyncio
async def test_client_cannot_cancel_another_client_order(
    db_session, sample_barber, sample_clients, mock_notifier
):
    qs = QueueService(db_session, notifier=mock_notifier)
    svc = sample_barber.services[0]
    client1 = sample_clients[0]
    client2 = sample_clients[1]

    order = await qs.join_queue(sample_barber.id, svc.id, client1)
    await db_session.commit()

    # Client 2 attempts to cancel Client 1's order
    with pytest.raises(QueueException, match="Permission denied"):
        await qs.cancel_by_client(order.id, client_id=client2.id)
