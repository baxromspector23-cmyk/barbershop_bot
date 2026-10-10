from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UtcDateTime


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    update_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
