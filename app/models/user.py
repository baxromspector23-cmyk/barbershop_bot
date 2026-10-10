from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import Language, UserRole

if TYPE_CHECKING:
    from app.models.barber import Barber
    from app.models.order import Order
    from app.models.payment import Payment


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default=Language.UZ.value, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.CLIENT.value, nullable=False, index=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    bot_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    barber_profile: Mapped[Barber | None] = relationship(
        "Barber", back_populates="user", uselist=False, foreign_keys="Barber.user_id"
    )
    orders: Mapped[list[Order]] = relationship("Order", back_populates="client")
    payments: Mapped[list[Payment]] = relationship("Payment", back_populates="client")

    @property
    def display_nick(self) -> str:
        if self.username:
            return f"@{self.username}"
        full = f"{self.first_name} {self.last_name or ''}".strip()
        return full or f"ID:{self.telegram_id}"
