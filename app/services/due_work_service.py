from __future__ import annotations

import logging
from datetime import timedelta

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.i18n import t
from app.keyboards.common import btn
from app.models.enums import OrderStatus, PaymentStatus
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.user_repo import UserRepository
from app.services.notification_service import NotificationService
from app.services.queue_service import QueueService
from app.utils.formatting import format_money
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
    unclosed_in_service_order_ids: list[tuple[int, int]] = []
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
                        qs = QueueService(item_session, notifier=notifier)
                        await qs._flag_refund_if_prepaid(order, reason="EOD_EXPIRED")
                        results["eod_cleaned"] += 1
                    elif order.status == OrderStatus.IN_SERVICE.value:
                        # Report to owner instead of silently closed, debounced by 24h
                        stale_interval = timedelta(hours=24)
                        if order.stale_alerted_at and (current_utc - order.stale_alerted_at) < stale_interval:
                            continue

                        order.stale_alerted_at = current_utc
                        barber_name = order.barber.display_name if order.barber else "Barber"
                        unclosed_in_service_items.append(
                            f"#{order.ticket_no} ({order.ticket_date}) - {barber_name}: {order.client_display_name}"
                        )
                        unclosed_in_service_order_ids.append((order.id, order.ticket_no))
        except Exception as e:
            logger.error("Error cleaning up order #%s: %s", order_id, e)

    # Report unclosed in-service orders to owner
    if unclosed_in_service_items and owner_ids:
        for oid in owner_ids:
            lang = "uz"
            async with session_factory() as s:
                user = await UserRepository(s).get_by_telegram_id(oid)
                if user and user.language:
                    lang = user.language

            report_text = t(
                "owner.unclosed_in_service_alert",
                lang=lang,
                items="\n".join(unclosed_in_service_items),
            )
            buttons = []
            for oid_item, ticket_no in unclosed_in_service_order_ids:
                buttons.append([
                    btn(
                        text=t("owner.btn_finish_order", lang=lang, ticket_no=ticket_no),
                        callback_data=f"b_done:{oid_item}",
                        icon="scissors",
                    ),
                    btn(
                        text=t("owner.btn_cancel_order", lang=lang, ticket_no=ticket_no),
                        callback_data=f"b_cancel:{oid_item}",
                        icon="forbidden",
                    ),
                ])
            markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
            await notifier.send_message(oid, report_text, reply_markup=markup)

    # 5. Unconfirmed Receipt Reminders (after 5m, every 5m up to 3 times)
    async with session_factory() as session:
        payment_repo = PaymentRepository(session)
        pending_receipts = await payment_repo.get_pending_receipts()
        candidate_receipt_ids = []
        for p in pending_receipts:
            sent_at = p.receipt_sent_at or p.created_at
            if not sent_at:
                continue
            raw = p.raw_payload or {}
            reminder_count = raw.get("receipt_reminder_count", 0)
            if reminder_count < 3:
                threshold_min = 5 + (reminder_count * 5)
                due_time = sent_at + timedelta(minutes=threshold_min)
                if current_utc >= due_time:
                    candidate_receipt_ids.append(p.id)

    max_per_tick = getattr(settings, "RECEIPT_REMINDER_MAX_PER_TICK", 10)
    candidate_receipt_ids = candidate_receipt_ids[:max_per_tick]

    for payment_id in candidate_receipt_ids:
        try:
            notifications_to_send = []
            async with session_factory() as item_session:
                async with item_session.begin():
                    payment_repo = PaymentRepository(item_session)
                    payment = await payment_repo.get_by_id(payment_id)
                    if not payment or payment.status != PaymentStatus.RECEIPT_SENT.value:
                        continue
                    raw = dict(payment.raw_payload or {})
                    count = raw.get("receipt_reminder_count", 0)
                    if count >= 3:
                        continue
                    raw["receipt_reminder_count"] = count + 1
                    raw["receipt_last_reminded_at"] = current_utc.isoformat()
                    payment.raw_payload = raw

                    order = payment.order
                    barber = payment.barber
                    barber_user = barber.user if barber else None
                    amount_str = format_money(payment.amount)
                    ticket_no = order.ticket_no if order else "?"
                    nick = order.client_display_name if order else "Mijoz"
                    service_name = order.service_name if order else "?"

                    if barber_user:
                        lang = barber_user.language or "uz"
                        reminder_text = t(
                            "payments.transfer_reminder_barber",
                            lang=lang,
                            ticket_no=ticket_no,
                            nick=nick,
                            service=service_name,
                            amount=amount_str,
                        )
                        kb = InlineKeyboardMarkup(inline_keyboard=[[
                            btn(text=t("payments.btn_transfer_ok", lang=lang), callback_data=f"tr_ok:{payment.id}", style="success", icon="check"),
                            btn(text=t("payments.btn_transfer_no", lang=lang), callback_data=f"tr_no:{payment.id}", style="danger", icon="cross"),
                        ]])
                        notifications_to_send.append({
                            "type": "photo" if payment.receipt_file_id else "message",
                            "chat_id": barber_user.telegram_id,
                            "file_id": payment.receipt_file_id,
                            "text": reminder_text,
                            "kb": kb,
                        })

                    # Also alert owner on 2nd or 3rd reminder if owner is not this barber
                    if count >= 1 and owner_ids:
                        for oid in owner_ids:
                            if barber_user and oid == barber_user.telegram_id:
                                continue
                            user_lang = "uz"
                            owner_u = await UserRepository(item_session).get_by_telegram_id(oid)
                            if owner_u and owner_u.language:
                                user_lang = owner_u.language
                            owner_text = t(
                                "payments.transfer_reminder_barber",
                                lang=user_lang,
                                ticket_no=ticket_no,
                                nick=nick,
                                service=service_name,
                                amount=amount_str,
                            )
                            kb_owner = InlineKeyboardMarkup(inline_keyboard=[[
                                btn(text=t("payments.btn_transfer_ok", lang=user_lang), callback_data=f"tr_ok:{payment.id}", style="success", icon="check"),
                                btn(text=t("payments.btn_transfer_no", lang=user_lang), callback_data=f"tr_no:{payment.id}", style="danger", icon="cross"),
                            ]])
                            notifications_to_send.append({
                                "type": "photo" if payment.receipt_file_id else "message",
                                "chat_id": oid,
                                "file_id": payment.receipt_file_id,
                                "text": owner_text,
                                "kb": kb_owner,
                            })

            # Telegram sends happen AFTER database transaction commit
            for n in notifications_to_send:
                if n["type"] == "photo":
                    await notifier.send_photo(
                        telegram_id=n["chat_id"],
                        file_id=n["file_id"],
                        caption=n["text"],
                        reply_markup=n["kb"],
                        parse_mode="HTML",
                    )
                else:
                    await notifier.send_message(
                        telegram_id=n["chat_id"],
                        text=n["text"],
                        reply_markup=n["kb"],
                        parse_mode="HTML",
                    )
            if notifications_to_send:
                results["reminders_sent"] += 1
        except Exception as e:
            logger.error("Error processing receipt reminder for payment #%s: %s", payment_id, e)

    return results
