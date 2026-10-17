from datetime import time, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
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
    monkeypatch: pytest.MonkeyPatch,
):
    """O3: Client join attempt outside working hours is rejected with BarberClosedError when check is enabled."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import app.services.queue_service as qs_module
    import app.utils.time_utils as tu_module

    tz = ZoneInfo("Asia/Tashkent")
    # Test at two different times of day: 01:30 (night) and 15:00 (afternoon)
    for test_dt in [
        datetime(2026, 10, 16, 1, 30, tzinfo=tz),
        datetime(2026, 10, 16, 15, 0, tzinfo=tz),
    ]:
        monkeypatch.setattr(qs_module, "now_tashkent", lambda dt=test_dt: dt)
        monkeypatch.setattr(tu_module, "now_tashkent", lambda dt=test_dt: dt)
        monkeypatch.setattr(settings, "CHECK_WORKING_HOURS", True)
        repo = BarberRepository(db_session)
        qs = QueueService(db_session)

        today_weekday = test_dt.weekday()

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

        # Case B: Working hours set to a time window that excludes test_dt
        # e.g. If test_dt is 01:30, window is 10:00 - 18:00
        # If test_dt is 15:00, window is 08:00 - 12:00
        wh_start = time(10, 0) if test_dt.hour < 10 else time(8, 0)
        wh_end = time(18, 0) if test_dt.hour < 10 else time(12, 0)
        await repo.update_working_hours(
            barber_id=sample_barber.id,
            weekday=today_weekday,
            start_time=wh_start,
            end_time=wh_end,
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


@pytest.mark.asyncio
async def test_barber_open_24_7_when_working_hours_check_disabled(
    db_session: AsyncSession,
    sample_barber: Barber,
    sample_clients: list[User],
    monkeypatch: pytest.MonkeyPatch,
):
    """When CHECK_WORKING_HOURS is False, barber is open 24/7 even if day-off is set in DB."""
    monkeypatch.setattr(settings, "CHECK_WORKING_HOURS", False)
    repo = BarberRepository(db_session)
    qs = QueueService(db_session)

    now_t = now_tashkent()
    today_weekday = now_t.weekday()

    # Mark today as day-off in DB schedule
    await repo.update_working_hours(
        barber_id=sample_barber.id,
        weekday=today_weekday,
        is_day_off=True,
    )
    await db_session.commit()

    sample_barber = await repo.get_by_id(sample_barber.id)
    # Since CHECK_WORKING_HOURS is False, barber remains open 24/7
    assert qs.is_barber_open(sample_barber, 0) is True
    assert qs.minutes_until_close(sample_barber) is None

    order = await qs.join_queue(
        barber_id=sample_barber.id,
        service_id=sample_barber.services[0].id,
        client=sample_clients[0],
        pay_now=False,
    )
    assert order is not None

