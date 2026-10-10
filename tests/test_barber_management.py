from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.barber import Barber
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus, UserRole
from app.models.order import Order
from app.models.payment import Payment
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.repositories.payment_repo import PaymentRepository
from app.services.queue_service import BarberClosedError, QueueService
from app.utils.time_utils import get_day_bounds_utc, get_week_bounds_utc, tashkent_today


@pytest.mark.asyncio
async def test_barber_card_metrics_and_revenue(
    db_session: AsyncSession,
    sample_barber: Barber,
    sample_clients: list[User],
):
    """O2: Detailed per-barber card metrics: username, phone, today/week revenue, queue size."""
    # 1. Update barber user with phone & username
    sample_barber.user.username = "ali_pro"
    sample_barber.user.phone = "+998901234567"
    await db_session.commit()

    # 2. Add an active order to queue
    qs = QueueService(db_session)
    await qs.join_queue(
        barber_id=sample_barber.id,
        service_id=sample_barber.services[0].id,
        client=sample_clients[0],
        pay_now=False,
    )
    await db_session.commit()

    q_len, wait_min = await qs.get_barber_queue_metrics(sample_barber.id)
    assert q_len == 1
    assert wait_min > 0

    # 3. Add a completed order with PAID payment today
    now = datetime.now(timezone.utc)
    completed_order = Order(
        barber_id=sample_barber.id,
        client_id=sample_clients[1].id,
        service_id=sample_barber.services[0].id,
        service_name=sample_barber.services[0].name,
        price=50000,
        duration_minutes=30,
        status=OrderStatus.COMPLETED.value,
        position_key=999,
        ticket_no=10,
        ticket_date=tashkent_today(),
        created_at=now,
        completed_at=now,
    )
    db_session.add(completed_order)
    await db_session.flush()

    payment = Payment(
        order_id=completed_order.id,
        barber_id=sample_barber.id,
        client_id=sample_clients[1].id,
        amount=50000,
        method=PaymentMethod.CASH.value,
        provider_payment_id=f"cash_{completed_order.id}",
        status=PaymentStatus.PAID.value,
        created_at=now,
        paid_at=now,
    )
    db_session.add(payment)
    await db_session.commit()

    # Check revenue metrics
    payment_repo = PaymentRepository(db_session)
    today = tashkent_today()
    day_start, day_end = get_day_bounds_utc(today)
    week_start, week_end = get_week_bounds_utc(today)

    today_rev = await payment_repo.get_barber_revenue_in_range(sample_barber.id, day_start, day_end)
    week_rev = await payment_repo.get_barber_revenue_in_range(sample_barber.id, week_start, week_end)

    assert today_rev == 50000
    assert week_rev == 50000


@pytest.mark.asyncio
async def test_barber_deactivation_policy_and_existing_queue(
    db_session: AsyncSession,
    sample_barber: Barber,
    sample_clients: list[User],
):
    """O2: Deactivated barber is excluded from client list, but existing queue is still served."""
    barber_repo = BarberRepository(db_session)
    qs = QueueService(db_session)

    # 1. Existing client joins when active
    order = await qs.join_queue(
        barber_id=sample_barber.id,
        service_id=sample_barber.services[0].id,
        client=sample_clients[0],
        pay_now=False,
    )
    await db_session.commit()
    assert order.status in [OrderStatus.WAITING.value, OrderStatus.CALLED.value]

    # 2. Deactivate barber
    await barber_repo.set_active(sample_barber.id, False)
    await db_session.commit()

    # 3. Barber excluded from active list
    active_barbers = await barber_repo.get_all_active()
    assert sample_barber.id not in [b.id for b in active_barbers]

    # 4. New client cannot join deactivated barber
    with pytest.raises(BarberClosedError):
        await qs.join_queue(
            barber_id=sample_barber.id,
            service_id=sample_barber.services[0].id,
            client=sample_clients[1],
            pay_now=False,
        )

    # 5. Existing queue can still be served (barber marks arrived/in-service)
    order_in_service = await qs.client_arrived(order.id)
    await db_session.commit()
    assert order_in_service.status == OrderStatus.IN_SERVICE.value


@pytest.mark.asyncio
async def test_revoke_barber_admin_rights(
    db_session: AsyncSession,
    sample_barber: Barber,
):
    """O2: Owner revokes admin rights -> role changes from BARBER to CLIENT and profile is deactivated."""
    assert sample_barber.user.role == UserRole.BARBER.value
    assert sample_barber.is_active is True

    # Revoke admin rights
    sample_barber.user.role = UserRole.CLIENT.value
    sample_barber.is_active = False
    await db_session.commit()

    await db_session.refresh(sample_barber.user)
    await db_session.refresh(sample_barber)

    assert sample_barber.user.role == UserRole.CLIENT.value
    assert sample_barber.is_active is False
