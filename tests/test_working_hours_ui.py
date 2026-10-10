from datetime import time, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.barber import Barber
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.barber_repo import BarberRepository
from app.services.queue_service import BarberClosedError, QueueService
from app.utils.time_utils import now_tashkent


@pytest.mark.asyncio
async def test_working_hours_repository_and_schedule_update(
    db_session: AsyncSession,
    sample_barber: Barber,
):
    """O3: Test schedule editing per weekday (open, close, day-off)."""
    repo = BarberRepository(db_session)

    # 1. Verify 7 default working days exist
    wh_list = await repo.get_working_hours(sample_barber.id)
    assert len(wh_list) == 7

    # 2. Update Monday (0) to 10:00 - 18:00
    mon = await repo.update_working_hours(
        barber_id=sample_barber.id,
        weekday=0,
        start_time=time(10, 0),
        end_time=time(18, 0),
        is_day_off=False,
    )
    await db_session.commit()

    assert mon.start_time == time(10, 0)
    assert mon.end_time == time(18, 0)
    assert mon.is_day_off is False

    # 3. Toggle Sunday (6) as day-off
    sun = await repo.update_working_hours(
        barber_id=sample_barber.id,
        weekday=6,
        is_day_off=True,
    )
    await db_session.commit()
    assert sun.is_day_off is True

    # 4. Toggle back Sunday to work day
    sun_work = await repo.update_working_hours(
        barber_id=sample_barber.id,
        weekday=6,
        is_day_off=False,
    )
    await db_session.commit()
    assert sun_work.is_day_off is False


@pytest.mark.asyncio
async def test_client_join_rejected_outside_working_hours(
    db_session: AsyncSession,
    sample_barber: Barber,
    sample_clients: list[User],
):
    """O3: Client join attempt outside working hours is rejected with BarberClosedError."""
    repo = BarberRepository(db_session)
    qs = QueueService(db_session)

    now_t = now_tashkent()
    today_weekday = now_t.weekday()

    # Case A: Today is marked as day-off
    await repo.update_working_hours(
        barber_id=sample_barber.id,
        weekday=today_weekday,
        is_day_off=True,
    )
    await db_session.commit()

    # Refresh barber with working hours
    sample_barber = await repo.get_by_id(sample_barber.id)
    assert qs.is_barber_open(sample_barber, 0) is False

    with pytest.raises(BarberClosedError):
        await qs.join_queue(
            barber_id=sample_barber.id,
            service_id=sample_barber.services[0].id,
            client=sample_clients[0],
            pay_now=False,
        )

    # Case B: Working hours set to a time window that is already passed today
    # e.g. 05:00 - 06:00 AM (assuming test does not run at 5 AM)
    # Or start_time 1 minute in the future
    await repo.update_working_hours(
        barber_id=sample_barber.id,
        weekday=today_weekday,
        start_time=time(1, 0),
        end_time=time(2, 0),
        is_day_off=False,
    )
    await db_session.commit()

    sample_barber = await repo.get_by_id(sample_barber.id)
    assert qs.is_barber_open(sample_barber, 0) is False

    with pytest.raises(BarberClosedError):
        await qs.join_queue(
            barber_id=sample_barber.id,
            service_id=sample_barber.services[0].id,
            client=sample_clients[0],
            pay_now=False,
        )
