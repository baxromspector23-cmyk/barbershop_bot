from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings

TASHKENT_TZ = ZoneInfo(settings.TIMEZONE)


def now_utc() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def now_tashkent() -> datetime:
    """Return current timezone-aware Tashkent datetime."""
    return datetime.now(TASHKENT_TZ)


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure datetime is timezone-aware UTC (handles SQLite naive timestamps)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_tashkent(dt: datetime) -> datetime:
    """Convert any datetime to Tashkent timezone."""
    dt = ensure_utc(dt)
    return dt.astimezone(TASHKENT_TZ)


def tashkent_today() -> date:
    """Return today's date in Asia/Tashkent."""
    return now_tashkent().date()


def format_time(dt: datetime | None) -> str:
    """Format time in Tashkent as HH:MM."""
    if not dt:
        return ""
    return to_tashkent(dt).strftime("%H:%M")


def format_datetime(dt: datetime | None) -> str:
    """Format datetime in Tashkent as DD.MM.YYYY HH:MM."""
    if not dt:
        return ""
    return to_tashkent(dt).strftime("%d.%m.%Y %H:%M")


def get_day_bounds_utc(target_date: date) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for a given calendar date in Asia/Tashkent."""
    start_tashkent = datetime.combine(target_date, time.min, tzinfo=TASHKENT_TZ)
    end_tashkent = datetime.combine(target_date, time.max, tzinfo=TASHKENT_TZ)
    return start_tashkent.astimezone(timezone.utc), end_tashkent.astimezone(timezone.utc)


def get_week_bounds_utc(target_date: date) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for Monday to Sunday containing target_date in Tashkent."""
    monday = target_date - timedelta(days=target_date.weekday())
    sunday = monday + timedelta(days=6)
    start_tashkent = datetime.combine(monday, time.min, tzinfo=TASHKENT_TZ)
    end_tashkent = datetime.combine(sunday, time.max, tzinfo=TASHKENT_TZ)
    return start_tashkent.astimezone(timezone.utc), end_tashkent.astimezone(timezone.utc)


def get_month_bounds_utc(year: int, month: int) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for calendar month in Tashkent."""
    _, last_day = calendar.monthrange(year, month)
    start_tashkent = datetime.combine(date(year, month, 1), time.min, tzinfo=TASHKENT_TZ)
    end_tashkent = datetime.combine(date(year, month, last_day), time.max, tzinfo=TASHKENT_TZ)
    return start_tashkent.astimezone(timezone.utc), end_tashkent.astimezone(timezone.utc)
