from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UtcDateTime
from app.models.enums import OrderStatus

if TYPE_CHECKING:
    from app.models.barber import Barber
    from app.models.payment import Payment
    from app.models.service import Service
    from app.models.user import User


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    barber_id: Mapped[int] = mapped_column(ForeignKey("barbers.id"), nullable=False, index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    walkin_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    walkin_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"), nullable=True)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        String(30), default=OrderStatus.WAITING.value, nullable=False, index=True
    )
    position_key: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    ticket_no: Mapped[int] = mapped_column(Integer, nullable=False)
    ticket_date: Mapped[date] = mapped_column(Date, nullable=False)
    late_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    called_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    heads_up_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # In-service reminder tracking (every 15m up to 3 times)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_reminded_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    stale_alerted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    barber: Mapped[Barber] = relationship("Barber", back_populates="orders", lazy="selectin")
    client: Mapped[User | None] = relationship("User", back_populates="orders", lazy="selectin")
    service: Mapped[Service | None] = relationship("Service", lazy="selectin")
    payments: Mapped[list[Payment]] = relationship("Payment", back_populates="order", lazy="selectin")

    __table_args__ = (
        Index(
            "uq_active_client_order",
            "client_id",
            unique=True,
            postgresql_where=text(
                "client_id IS NOT NULL AND status IN ('WAITING', 'CALLED', 'IN_SERVICE', 'PENDING_PAYMENT')"
            ),
            sqlite_where=text(
                "client_id IS NOT NULL AND status IN ('WAITING', 'CALLED', 'IN_SERVICE', 'PENDING_PAYMENT')"
            ),
        ),
        Index(
            "ix_barber_status_position",
            "barber_id",
            "status",
            "position_key",
        ),
        Index(
            "ix_called_deadline",
            "deadline_at",
            postgresql_where=text("status = 'CALLED'"),
            sqlite_where=text("status = 'CALLED'"),
        ),
    )

    @property
    def client_display_name(self) -> str:
        if self.client:
            return self.client.display_nick
        if self.walkin_name:
            if self.walkin_phone:
                return f"{self.walkin_name} ({self.walkin_phone})"
            return self.walkin_name
        return "Mijoz"
