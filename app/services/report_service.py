from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PaymentMethod
from app.repositories.barber_repo import BarberRepository
from app.repositories.payment_repo import PaymentRepository
from app.utils.time_utils import (
    ensure_utc,
    format_datetime,
    get_day_bounds_utc,
    get_month_bounds_utc,
    get_week_bounds_utc,
    tashkent_today,
)


@dataclass
class BarberRankingItem:
    barber_id: int
    display_name: str
    revenue: int
    services_count: int
    is_top: bool = False


@dataclass
class ReportSummary:
    period_title: str
    start_utc: datetime
    end_utc: datetime
    total_revenue: int
    total_services: int
    payme_sum: int
    click_sum: int
    paynet_sum: int
    cash_sum: int
    rankings: list[BarberRankingItem]


class ReportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.payment_repo = PaymentRepository(session)
        self.barber_repo = BarberRepository(session)

    def get_period_bounds(self, period_type: str, offset: int = 0) -> tuple[datetime, datetime, str]:
        """
        Calculates UTC start and end bounds based on Asia/Tashkent calendar:
        period_type: 'today' | 'week' | 'month'
        offset: 0 = current, -1 = previous, +1 = next
        """
        today = tashkent_today()

        if period_type == "today":
            target_date = today + timedelta(days=offset)
            start_utc, end_utc = get_day_bounds_utc(target_date)
            title = target_date.strftime("%d.%m.%Y")
            return start_utc, end_utc, title

        elif period_type == "week":
            # Monday of current week + (7 * offset) days
            monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
            sunday = monday + timedelta(days=6)
            start_utc, end_utc = get_week_bounds_utc(monday)
            title = f"{monday.strftime('%d.%m')} - {sunday.strftime('%d.%m.%Y')}"
            return start_utc, end_utc, title

        elif period_type == "month":
            # Shift month by offset
            year = today.year
            month = today.month + offset
            while month < 1:
                month += 12
                year -= 1
            while month > 12:
                month -= 12
                year += 1

            start_utc, end_utc = get_month_bounds_utc(year, month)
            import calendar
            month_name = calendar.month_name[month]
            title = f"{month_name} {year}"
            return start_utc, end_utc, title

        else:
            start_utc, end_utc = get_day_bounds_utc(today)
            return start_utc, end_utc, today.strftime("%d.%m.%Y")

    async def generate_report(self, period_type: str = "today", offset: int = 0) -> ReportSummary:
        start_utc, end_utc, period_title = self.get_period_bounds(period_type, offset)

        payments = await self.payment_repo.get_revenue_payments_in_range(start_utc, end_utc)
        all_barbers = await self.barber_repo.get_all()
        {b.id: b.display_name for b in all_barbers}

        total_revenue = sum(p.amount for p in payments)
        total_services = len(payments)

        payme_sum = sum(p.amount for p in payments if p.method == PaymentMethod.PAYME.value)
        click_sum = sum(p.amount for p in payments if p.method == PaymentMethod.CLICK.value)
        paynet_sum = sum(p.amount for p in payments if p.method == PaymentMethod.PAYNET.value)
        cash_sum = sum(p.amount for p in payments if p.method == PaymentMethod.CASH.value)

        # Barber rankings
        barber_stats: dict[int, dict[str, Any]] = {
            b.id: {"revenue": 0, "count": 0, "name": b.display_name} for b in all_barbers
        }

        for p in payments:
            if p.barber_id in barber_stats:
                barber_stats[p.barber_id]["revenue"] += p.amount
                barber_stats[p.barber_id]["count"] += 1
            else:
                barber_name = p.barber.display_name if p.barber else f"Barber #{p.barber_id}"
                barber_stats[p.barber_id] = {
                    "revenue": p.amount,
                    "count": 1,
                    "name": barber_name,
                }

        # Sort highest revenue first, then highest service count
        sorted_barbers = sorted(
            barber_stats.items(),
            key=lambda item: (item[1]["revenue"], item[1]["count"]),
            reverse=True,
        )

        rankings: list[BarberRankingItem] = []
        is_first = True
        for b_id, stat in sorted_barbers:
            rankings.append(
                BarberRankingItem(
                    barber_id=b_id,
                    display_name=stat["name"],
                    revenue=stat["revenue"],
                    services_count=stat["count"],
                    is_top=is_first and stat["revenue"] > 0,
                )
            )
            is_first = False

        return ReportSummary(
            period_title=period_title,
            start_utc=start_utc,
            end_utc=end_utc,
            total_revenue=total_revenue,
            total_services=total_services,
            payme_sum=payme_sum,
            click_sum=click_sum,
            paynet_sum=paynet_sum,
            cash_sum=cash_sum,
            rankings=rankings,
        )

    async def generate_csv(self, period_type: str = "today", offset: int = 0) -> str:
        start_utc, end_utc, _ = self.get_period_bounds(period_type, offset)
        payments = await self.payment_repo.get_revenue_payments_in_range(start_utc, end_utc)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Sana (Asia/Tashkent)", "Barber", "Mijoz", "Xizmat", "Narxi (UZS)", "To'lov turi"])

        for p in payments:
            paid_time = ensure_utc(p.paid_at)
            completed_time = ensure_utc(p.order.completed_at)
            revenue_time = max(paid_time, completed_time)
            formatted_date = format_datetime(revenue_time)
            barber_name = p.barber.display_name if p.barber else f"Barber #{p.barber_id}"
            client_nick = p.order.client_display_name if p.order else "Mijoz"
            service_name = p.order.service_name if p.order else ""

            writer.writerow([
                formatted_date,
                barber_name,
                client_nick,
                service_name,
                p.amount,
                p.method,
            ])

        return output.getvalue()
