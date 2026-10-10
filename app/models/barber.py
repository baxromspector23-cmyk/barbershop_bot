from __future__ import annotations

from datetime import datetime, time, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.payment import Payment
    from app.models.service import Service
    from app.models.user import User


class Barber(Base):
    __tablename__ = "barbers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped[User] = relationship(
        "User", back_populates="barber_profile", foreign_keys=[user_id], lazy="selectin"
    )
    working_hours: Mapped[list[BarberWorkingHours]] = relationship(
        "BarberWorkingHours", back_populates="barber", cascade="all, delete-orphan", lazy="selectin"
    )
    services: Mapped[list[Service]] = relationship(
        "Service", back_populates="barber", cascade="all, delete-orphan", lazy="selectin"
    )
    orders: Mapped[list[Order]] = relationship("Order", back_populates="barber", lazy="selectin")
    payments: Mapped[list[Payment]] = relationship("Payment", back_populates="barber", lazy="selectin")


class BarberWorkingHours(Base):
    __tablename__ = "barber_working_hours"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    barber_id: Mapped[int] = mapped_column(ForeignKey("barbers.id"), nullable=False, index=True)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = Monday, 6 = Sunday
    start_time: Mapped[time] = mapped_column(Time, default=time(9, 0), nullable=False)
    end_time: Mapped[time] = mapped_column(Time, default=time(20, 0), nullable=False)
    is_day_off: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    barber: Mapped[Barber] = relationship("Barber", back_populates="working_hours", lazy="selectin")
