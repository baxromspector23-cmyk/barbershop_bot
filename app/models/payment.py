from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UtcDateTime
from app.models.enums import PaymentStatus

if TYPE_CHECKING:
    from app.models.barber import Barber
    from app.models.order import Order
    from app.models.user import User


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    barber_id: Mapped[int] = mapped_column(ForeignKey("barbers.id"), nullable=False, index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # in so'm (UZS)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=PaymentStatus.PENDING.value, nullable=False, index=True
    )
    provider_payment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    refund_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    paid_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    order: Mapped[Order] = relationship("Order", back_populates="payments", lazy="selectin")
    barber: Mapped[Barber] = relationship("Barber", back_populates="payments", lazy="selectin")
    client: Mapped[User | None] = relationship("User", back_populates="payments", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("method", "provider_payment_id", name="uq_payment_method_provider_id"),
        Index("ix_payment_revenue", "status", "paid_at"),
    )
