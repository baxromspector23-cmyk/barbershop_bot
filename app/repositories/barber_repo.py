from datetime import time
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.barber import Barber, BarberWorkingHours
from app.models.service import Service


class BarberRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lock_barber_for_update(self, barber_id: int) -> Barber | None:
        """Locks the barber row for concurrency control (FOR UPDATE in Postgres)."""
        bind = self.session.bind
        dialect_name = bind.dialect.name if bind else ""
        stmt = (
            select(Barber)
            .where(Barber.id == barber_id)
            .options(selectinload(Barber.working_hours))
            .execution_options(populate_existing=True)
        )
        if dialect_name == "postgresql":
            stmt = stmt.with_for_update()
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_id(self, barber_id: int) -> Barber | None:
        stmt = (
            select(Barber)
            .where(Barber.id == barber_id)
            .options(selectinload(Barber.working_hours), selectinload(Barber.services))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_user_id(self, user_id: int) -> Barber | None:
        stmt = (
            select(Barber)
            .where(Barber.user_id == user_id)
            .options(selectinload(Barber.working_hours), selectinload(Barber.services))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_all_active(self) -> list[Barber]:
        stmt = (
            select(Barber)
            .where(Barber.is_active)
            .options(selectinload(Barber.working_hours), selectinload(Barber.services))
            .order_by(Barber.id.asc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_all(self) -> list[Barber]:
        stmt = (
            select(Barber)
            .options(selectinload(Barber.working_hours), selectinload(Barber.services))
            .order_by(Barber.id.asc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_barber(
        self, user_id: int, display_name: str, photo_file_id: str | None = None
    ) -> Barber:
        barber = Barber(
            user_id=user_id,
            display_name=display_name,
            photo_file_id=photo_file_id,
            is_active=True,
            is_paused=False,
        )
        self.session.add(barber)
        await self.session.flush()

        # Create default working hours (Mon-Sun, open 24h: start == end). Owner can set real hours from the bot.
        from datetime import time
        for weekday in range(7):
            wh = BarberWorkingHours(
                barber_id=barber.id,
                weekday=weekday,
                start_time=time(0, 0),
                end_time=time(0, 0),
                is_day_off=False,
            )
            self.session.add(wh)
        await self.session.flush()
        return barber

    async def set_paused(self, barber_id: int, is_paused: bool) -> None:
        stmt = update(Barber).where(Barber.id == barber_id).values(is_paused=is_paused)
        await self.session.execute(stmt)

    async def set_active(self, barber_id: int, is_active: bool) -> None:
        stmt = update(Barber).where(Barber.id == barber_id).values(is_active=is_active)
        await self.session.execute(stmt)

    async def get_working_hours(self, barber_id: int) -> list[BarberWorkingHours]:
        stmt = (
            select(BarberWorkingHours)
            .where(BarberWorkingHours.barber_id == barber_id)
            .order_by(BarberWorkingHours.weekday.asc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_working_hour(self, barber_id: int, weekday: int) -> BarberWorkingHours | None:
        stmt = (
            select(BarberWorkingHours)
            .where(
                and_(
                    BarberWorkingHours.barber_id == barber_id,
                    BarberWorkingHours.weekday == weekday,
                )
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_working_hours(
        self,
        barber_id: int,
        weekday: int,
        start_time: time | None = None,
        end_time: time | None = None,
        is_day_off: bool | None = None,
    ) -> BarberWorkingHours:
        wh = await self.get_working_hour(barber_id, weekday)
        if not wh:
            wh = BarberWorkingHours(
                barber_id=barber_id,
                weekday=weekday,
                start_time=start_time or time(9, 0),
                end_time=end_time or time(20, 0),
                is_day_off=is_day_off if is_day_off is not None else False,
            )
            self.session.add(wh)
        else:
            if start_time is not None:
                wh.start_time = start_time
            if end_time is not None:
                wh.end_time = end_time
            if is_day_off is not None:
                wh.is_day_off = is_day_off
        await self.session.flush()
        return wh

    async def update_profile(
        self,
        barber_id: int,
        display_name: str | None = None,
        photo_file_id: str | None = None,
    ) -> None:
        values: dict[str, Any] = {}
        if display_name is not None:
            values["display_name"] = display_name
        if photo_file_id is not None:
            values["photo_file_id"] = photo_file_id
        if values:
            stmt = update(Barber).where(Barber.id == barber_id).values(**values)
            await self.session.execute(stmt)

    async def get_services(self, barber_id: int, active_only: bool = True) -> list[Service]:
        stmt = select(Service).where(Service.barber_id == barber_id)
        if active_only:
            stmt = stmt.where(Service.is_active)
        stmt = stmt.order_by(Service.id.asc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_service_by_id(self, service_id: int) -> Service | None:
        stmt = select(Service).where(Service.id == service_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_service(
        self, barber_id: int, name: str, price: int, duration_minutes: int
    ) -> Service:
        svc = Service(
            barber_id=barber_id,
            name=name,
            price=price,
            duration_minutes=duration_minutes,
            is_active=True,
        )
        self.session.add(svc)
        await self.session.flush()
        return svc

    async def toggle_service(self, service_id: int) -> Service | None:
        svc = await self.get_service_by_id(service_id)
        if svc:
            svc.is_active = not svc.is_active
            await self.session.flush()
        return svc

    async def update_service(self, service_id: int, **values) -> Service | None:
        svc = await self.get_service_by_id(service_id)
        if svc and values:
            stmt = update(Service).where(Service.id == service_id).values(**values)
            await self.session.execute(stmt)
            await self.session.flush()
        return svc
