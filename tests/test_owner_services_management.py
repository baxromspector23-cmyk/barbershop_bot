import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.barber import Barber
from app.models.enums import OrderStatus, UserRole
from app.models.service import Service
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.services.queue_service import QueueService


@pytest.mark.asyncio
async def test_service_price_and_duration_validation_bounds(db_session: AsyncSession, sample_barber: Barber):
    """O1: Validate service bounds for price (> 0) and duration (5..480 minutes)."""
    repo = BarberRepository(db_session)

    # Valid creation
    svc = await repo.create_service(
        barber_id=sample_barber.id,
        name="Soch turmagi",
        price=50000,
        duration_minutes=30,
    )
    await db_session.commit()
    assert svc.id is not None
    assert svc.price == 50000
    assert svc.duration_minutes == 30

    # Update name, price, duration
    await repo.update_service(svc.id, name="Yangilangan soch", price=70000, duration_minutes=45)
    await db_session.commit()

    updated = await repo.get_service_by_id(svc.id)
    assert updated.name == "Yangilangan soch"
    assert updated.price == 70000
    assert updated.duration_minutes == 45

    # Toggle active status
    toggled = await repo.toggle_service(svc.id)
    await db_session.commit()
    assert toggled.is_active is False

    toggled_again = await repo.toggle_service(svc.id)
    await db_session.commit()
    assert toggled_again.is_active is True


@pytest.mark.asyncio
async def test_service_edit_preserves_historical_order_snapshot(
    db_session: AsyncSession,
    sample_barber: Barber,
    sample_clients: list[User],
):
    """O1: Changing price/duration affects only new orders; existing orders keep historical snapshot."""
    repo = BarberRepository(db_session)
    qs = QueueService(db_session)

    # 1. Create original service
    orig_svc = await repo.create_service(
        barber_id=sample_barber.id,
        name="Soch olish",
        price=40000,
        duration_minutes=25,
    )
    await db_session.commit()

    # 2. Client joins queue under original pricing
    client1 = sample_clients[0]
    order1 = await qs.join_queue(
        barber_id=sample_barber.id,
        service_id=orig_svc.id,
        client=client1,
        pay_now=False,
    )
    await db_session.commit()

    assert order1.service_name == "Soch olish"
    assert order1.price == 40000
    assert order1.duration_minutes == 25

    # 3. Owner edits service: increases price to 60000, duration to 40, renames to "Soch + Soqol"
    await repo.update_service(
        orig_svc.id,
        name="Soch + Soqol",
        price=60000,
        duration_minutes=40,
    )
    await db_session.commit()

    # 4. Verify existing order1 still retains original historical snapshot
    await db_session.refresh(order1)
    assert order1.service_name == "Soch olish"
    assert order1.price == 40000
    assert order1.duration_minutes == 25

    # 5. New client joins queue -> receives the updated service pricing
    client2 = sample_clients[1]
    order2 = await qs.join_queue(
        barber_id=sample_barber.id,
        service_id=orig_svc.id,
        client=client2,
        pay_now=False,
    )
    await db_session.commit()

    assert order2.service_name == "Soch + Soqol"
    assert order2.price == 60000
    assert order2.duration_minutes == 40


@pytest.mark.asyncio
async def test_service_fsm_price_and_duration_validation_handlers(
    db_session: AsyncSession,
    sample_barber: Barber,
):
    """Test price > 0 and duration 5..480 validation in FSM handlers."""
    from unittest.mock import AsyncMock

    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    from app.handlers.barber import handle_add_svc_duration, handle_add_svc_price

    owner_user = User(
        id=9999,
        telegram_id=999999,
        role=UserRole.OWNER.value,
        first_name="Owner",
        language="uz",
    )
    db_session.add(owner_user)
    await db_session.commit()

    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=1, user_id=owner_user.id)
    state = FSMContext(storage=storage, key=key)

    # 1. Price <= 0 rejected
    msg_zero_price = AsyncMock()
    msg_zero_price.text = "0"
    msg_zero_price.answer = AsyncMock()
    await handle_add_svc_price(msg_zero_price, db_session, owner_user, state, "uz")
    assert "0 dan katta" in msg_zero_price.answer.call_args[0][0]

    # Valid price accepted
    msg_valid_price = AsyncMock()
    msg_valid_price.text = "50000"
    msg_valid_price.answer = AsyncMock()
    await handle_add_svc_price(msg_valid_price, db_session, owner_user, state, "uz")
    data = await state.get_data()
    assert data.get("svc_price") == 50000

    # 2. Duration < 5 rejected
    msg_too_short = AsyncMock()
    msg_too_short.text = "3"
    msg_too_short.answer = AsyncMock()
    await handle_add_svc_duration(msg_too_short, db_session, owner_user, state, "uz")
    assert "5" in msg_too_short.answer.call_args[0][0]

    # Duration > 480 rejected
    msg_too_long = AsyncMock()
    msg_too_long.text = "500"
    msg_too_long.answer = AsyncMock()
    await handle_add_svc_duration(msg_too_long, db_session, owner_user, state, "uz")
    assert "480" in msg_too_long.answer.call_args[0][0]
