from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


from app.db.types import UtcDateTime


class Base(DeclarativeBase):
    def __getattribute__(self, name: str):
        if name == "id":
            d = object.__getattribute__(self, "__dict__")
            if "id" in d:
                return d["id"]
            try:
                from sqlalchemy.orm import attributes

                state = attributes.instance_state(self)
                if state.key is not None and state.key[1]:
                    return state.key[1][0]
            except Exception:
                pass
        return super().__getattribute__(name)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
