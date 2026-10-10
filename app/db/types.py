from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, TypeDecorator


class UtcDateTime(TypeDecorator):
    """
    Stores UTC datetime and always returns timezone-aware UTC datetime.
    Guarantees consistent timezone-aware objects across SQLite and PostgreSQL.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime, got {type(value)}")
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
