from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import OrderStatus
from app.models.order import Order


class OrderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, order_id: int) -> Order | None:
        stmt = (
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.client), selectinload(Order.barber))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_active_order_for_client(self, client_id: int) -> Order | None:
        active_statuses = [
            OrderStatus.WAITING.value,
            OrderStatus.CALLED.value,
            OrderStatus.IN_SERVICE.value,
            OrderStatus.PENDING_PAYMENT.value,
        ]
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.client_id == client_id,
                    Order.status.in_(active_statuses),
                )
            )
            .options(selectinload(Order.barber), selectinload(Order.client))
            .order_by(Order.id.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_active_orders_for_barber(self, barber_id: int) -> list[Order]:
        active_statuses = [
            OrderStatus.WAITING.value,
            OrderStatus.CALLED.value,
            OrderStatus.IN_SERVICE.value,
        ]
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.barber_id == barber_id,
                    Order.status.in_(active_statuses),
                )
            )
            .options(selectinload(Order.client), selectinload(Order.barber))
            .order_by(Order.position_key.asc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_next_waiting_order(self, barber_id: int) -> Order | None:
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.barber_id == barber_id,
                    Order.status == OrderStatus.WAITING.value,
                )
            )
            .options(selectinload(Order.client), selectinload(Order.barber))
            .order_by(Order.position_key.asc())
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_next_waiting_after(
        self, barber_id: int, current_position_key: int
    ) -> Order | None:
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.barber_id == barber_id,
                    Order.status == OrderStatus.WAITING.value,
                    Order.position_key > current_position_key,
                )
            )
            .options(selectinload(Order.client), selectinload(Order.barber))
            .order_by(Order.position_key.asc())
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_next_position_key(self, barber_id: int) -> int:
        stmt = select(func.max(Order.position_key)).where(Order.barber_id == barber_id)
        res = await self.session.execute(stmt)
        max_key = res.scalar()
        return (max_key or 0) + 1

    async def get_next_ticket_no(self, barber_id: int, ticket_date: date) -> int:
        stmt = select(func.count(Order.id)).where(
            and_(
                Order.barber_id == barber_id,
                Order.ticket_date == ticket_date,
            )
        )
        res = await self.session.execute(stmt)
        count = res.scalar() or 0
        return count + 1

    async def get_client_history(self, client_id: int, limit: int = 10) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.client_id == client_id)
            .options(selectinload(Order.barber))
            .order_by(Order.id.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_due_called_orders(self, now_dt: datetime) -> list[Order]:
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.status == OrderStatus.CALLED.value,
                    Order.deadline_at.isnot(None),
                    Order.deadline_at <= now_dt,
                )
            )
            .options(selectinload(Order.client), selectinload(Order.barber))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_expired_pending_payments(self, cutoff_dt: datetime) -> list[Order]:
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.status == OrderStatus.PENDING_PAYMENT.value,
                    Order.created_at <= cutoff_dt,
                )
            )
            .options(selectinload(Order.client), selectinload(Order.barber))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_end_of_day_uncompleted(self, today: date) -> list[Order]:
        """Find orders from previous calendar days that are still WAITING, CALLED, or IN_SERVICE."""
        active_statuses = [
            OrderStatus.WAITING.value,
            OrderStatus.CALLED.value,
            OrderStatus.IN_SERVICE.value,
        ]
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.ticket_date < today,
                    Order.status.in_(active_statuses),
                )
            )
            .options(selectinload(Order.client), selectinload(Order.barber))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_orders_in_service(self) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.status == OrderStatus.IN_SERVICE.value)
            .options(selectinload(Order.client), selectinload(Order.barber))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
