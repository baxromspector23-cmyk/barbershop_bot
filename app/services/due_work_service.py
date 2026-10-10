from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.i18n import t
from app.models.enums import OrderStatus
from app.repositories.order_repo import OrderRepository
from app.services.notification_service import NotificationService
from app.services.queue_service import QueueService
from app.utils.time_utils import now_utc, tashkent_today

logger = logging.getLogger(__name__)


async def process_due_work(
    session_factory: async_sessionmaker[AsyncSession],
    notifier: NotificationService | None = None,
    owner_telegram_ids: list[int] | None = None,
) -> dict:
    """
    Idempotent worker function executing all time-driven tasks:
    1. Overdue CALLED orders (deadline passed)
    2. Expired PENDING_PAYMENT orders (> 10m)
    3. In-service barber reminders (> duration + 15m, every 15m up to 3 times)
    4. Daily cleanup (orders of previous days)
    Each task runs in its own transaction to survive failures and isolate side effects.
    """
    notifier = notifier or NotificationService()
    owner_ids = owner_telegram_ids or settings.OWNER_TELEGRAM_IDS
    current_utc = now_utc()
    results = {
        "lateness_processed": 0,
        "pending_expired": 0,
        "reminders_sent": 0,
        "eod_cleaned": 0,
    }

    # 1. Process Due CALLED Orders
    async with session_factory() as session:
        repo = OrderRepository(session)
        due_called = await repo.get_due_called_orders(current_utc)
        due_order_ids = [o.id for o in due_called]

    for order_id in due_order_ids:
        try:
            async with session_factory() as item_session:
                async with item_session.begin():
                    qs = QueueService(item_session, notifier=notifier)
                    handled = await qs.handle_lateness(order_id)
                    if handled:
                        results["lateness_processed"] += 1
        except Exception as e:
            logger.error("Error processing lateness for order #%s: %s", order_id, e)

    # 2. Expire Pending Payments (> 10 minutes)
    cutoff_pending = current_utc - timedelta(minutes=10)
    async with session_factory() as session:
        repo = OrderRepository(session)
        expired_pending = await repo.get_expired_pending_payments(cutoff_pending)
        expired_pending_ids = [o.id for o in expired_pending]

    for order_id in expired_pending_ids:
        try:
            async with session_factory() as item_session:
                async with item_session.begin():
                    repo = OrderRepository(item_session)
                    order = await repo.get_by_id(order_id)
                    if order and order.status == OrderStatus.PENDING_PAYMENT.value:
                        order.status = OrderStatus.EXPIRED.value
                        order.cancelled_at = current_utc
                        results["pending_expired"] += 1
        except Exception as e:
            logger.error("Error expiring pending order #%s: %s", order_id, e)

    # 3. In-Service Barber Reminders
    async with session_factory() as session:
        repo = OrderRepository(session)
        in_service_orders = await repo.get_orders_in_service()
        candidate_reminders = []
        for o in in_service_orders:
            if o.started_at and o.reminder_count < 3:
                # Base threshold: duration + 15 min
                # Subsequent: every 15 min
                threshold_minutes = o.duration_minutes + 15 + (o.reminder_count * 15)
                due_time = o.started_at + timedelta(minutes=threshold_minutes)
                if current_utc >= due_time:
                    candidate_reminders.append(o.id)

    for order_id in candidate_reminders:
        try:
            async with session_factory() as item_session:
                async with item_session.begin():
                    repo = OrderRepository(item_session)
                    order = await repo.get_by_id(order_id)
                    if (
                        order
                        and order.status == OrderStatus.IN_SERVICE.value
                        and order.reminder_count < 3
                    ):
                        order.reminder_count += 1
                        order.last_reminded_at = current_utc

                        # Notify barber
                        if order.barber and order.barber.user:
                            barber_user = order.barber.user
                            reminder_text = t(
                                "barber.in_service_reminder",
                                lang=barber_user.language,
                                ticket_no=order.ticket_no,
                                nick=order.client_display_name,
                                duration=order.duration_minutes,
                            )
                            await notifier.send_message(
                                telegram_id=barber_user.telegram_id,
                                text=reminder_text,
                            )
                        results["reminders_sent"] += 1
        except Exception as e:
            logger.error("Error processing in-service reminder for #%s: %s", order_id, e)

    # 4. Daily Cleanup (previous days' uncompleted orders)
    today = tashkent_today()
    async with session_factory() as session:
        repo = OrderRepository(session)
        eod_orders = await repo.get_end_of_day_uncompleted(today)
        eod_order_ids = [(o.id, o.status) for o in eod_orders]

    unclosed_in_service_items: list[str] = []
    for order_id, status in eod_order_ids:
        try:
            async with session_factory() as item_session:
                async with item_session.begin():
                    repo = OrderRepository(item_session)
                    order = await repo.get_by_id(order_id)
                    if not order or order.ticket_date >= today:
                        continue

                    if order.status in [OrderStatus.WAITING.value, OrderStatus.CALLED.value]:
                        order.status = OrderStatus.EXPIRED.value
                        order.cancelled_at = current_utc
                        results["eod_cleaned"] += 1
                    elif order.status == OrderStatus.IN_SERVICE.value:
                        # Report to owner instead of silently closed
                        barber_name = order.barber.display_name if order.barber else "Barber"
                        unclosed_in_service_items.append(
                            f"#{order.ticket_no} ({order.ticket_date}) - {barber_name}: {order.client_display_name}"
                        )
        except Exception as e:
            logger.error("Error cleaning up order #%s: %s", order_id, e)

    # Report unclosed in-service orders to owner
    if unclosed_in_service_items and owner_ids:
        report_text = (
            "⚠️ Diqqat! Kechagi kundan yakunlanmagan (IN_SERVICE) buyurtmalar mavjud:\n"
            + "\n".join(unclosed_in_service_items)
        )
        for oid in owner_ids:
            await notifier.send_message(oid, report_text)

    return results
