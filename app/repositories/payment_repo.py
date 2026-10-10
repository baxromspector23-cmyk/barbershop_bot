from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import OrderStatus, PaymentStatus
from app.models.order import Order
from app.models.payment import Payment
from app.utils.time_utils import ensure_utc, now_utc


class PaymentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_payment(
        self,
        order_id: int,
        barber_id: int,
        amount: int,
        method: str,
        provider_payment_id: str,
        client_id: int | None = None,
        status: str = PaymentStatus.PENDING.value,
        raw_payload: dict[str, Any] | None = None,
    ) -> Payment:
        payment = Payment(
            order_id=order_id,
            barber_id=barber_id,
            client_id=client_id,
            amount=amount,
            method=method,
            provider_payment_id=provider_payment_id,
            status=status,
            raw_payload=raw_payload,
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def get_by_provider_id(
        self, method: str, provider_payment_id: str
    ) -> Payment | None:
        stmt = (
            select(Payment)
            .where(
                and_(
                    Payment.method == method,
                    Payment.provider_payment_id == provider_payment_id,
                )
            )
            .options(
                selectinload(Payment.order),
                selectinload(Payment.barber),
                selectinload(Payment.client),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_id(self, payment_id: int) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.id == payment_id)
            .options(
                selectinload(Payment.order),
                selectinload(Payment.barber),
                selectinload(Payment.client),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_order_id(self, order_id: int) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.order_id == order_id)
            .options(
                selectinload(Payment.order),
                selectinload(Payment.barber),
                selectinload(Payment.client),
            )
            .order_by(Payment.id.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_barber_payments(
        self, barber_id: int, limit: int = 20
    ) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(
                and_(
                    Payment.barber_id == barber_id,
                    Payment.status == PaymentStatus.PAID.value,
                )
            )
            .options(
                selectinload(Payment.order),
                selectinload(Payment.client),
            )
            .order_by(Payment.paid_at.desc(), Payment.id.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_revenue_payments_in_range(
        self, start_utc: datetime, end_utc: datetime
    ) -> list[Payment]:
        stmt = (
            select(Payment)
            .join(Order, Payment.order_id == Order.id)
            .where(
                and_(
                    Payment.status == PaymentStatus.PAID.value,
                    Order.status == OrderStatus.COMPLETED.value,
                    Payment.paid_at.isnot(None),
                    Order.completed_at.isnot(None),
                )
            )
            .options(
                selectinload(Payment.order),
                selectinload(Payment.barber),
                selectinload(Payment.client),
            )
            .order_by(Payment.id.asc())
        )
        res = await self.session.execute(stmt)
        all_payments = res.scalars().all()

        start_utc = ensure_utc(start_utc)
        end_utc = ensure_utc(end_utc)

        filtered: list[Payment] = []
        for p in all_payments:
            paid_time = ensure_utc(p.paid_at)
            completed_time = ensure_utc(p.order.completed_at)
            revenue_at = max(paid_time, completed_time)
            if start_utc <= revenue_at <= end_utc:
                filtered.append(p)
        return filtered

    async def get_refund_pending_payments(self) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(Payment.status == PaymentStatus.REFUND_PENDING.value)
            .options(
                selectinload(Payment.order),
                selectinload(Payment.barber),
                selectinload(Payment.client),
            )
            .order_by(Payment.id.desc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def mark_as_paid(
        self,
        payment: Payment,
        paid_at: datetime | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> Payment:
        payment.status = PaymentStatus.PAID.value
        payment.paid_at = paid_at or now_utc()
        if raw_payload:
            payment.raw_payload = raw_payload
        await self.session.flush()
        return payment

    async def mark_as_refund_pending(self, payment: Payment) -> Payment:
        payment.status = PaymentStatus.REFUND_PENDING.value
        await self.session.flush()
        return payment

    async def mark_as_refunded(self, payment: Payment) -> Payment:
        payment.status = PaymentStatus.REFUNDED.value
        await self.session.flush()
        return payment
