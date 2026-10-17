from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db.session import async_session_maker
from app.models.audit import AuditLog
from app.models.enums import OrderStatus, UserRole
from app.models.invite import BarberInvite
from app.models.order import Order
from app.models.payment import Payment
from app.models.processed_update import ProcessedUpdate
from app.models.user import User
from app.services.due_work_service import process_due_work
from app.services.notification_service import NotificationService
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


async def cleanup_database_bloat(
    session_factory: async_sessionmaker[AsyncSession] = async_session_maker,
) -> None:
    """
    1. Merges duplicate CLIENT rows sharing the same 9-digit phone number into a single User.
    2. Links any walk-in orders (client_id IS NULL) to the matching User by phone.
    3. Purges old cancelled/no-show unpaid orders, old audit logs, processed updates, and expired invites so the DB never fills up.
    """
    async with session_factory() as session:
        from app.models.barber import Barber
        from app.repositories.barber_repo import BarberRepository

        barber_repo = BarberRepository(session)
        # Demote removed ID 8598163827 if it was OWNER
        removed_res = await session.execute(select(User).where(User.telegram_id == 8598163827))
        removed_user = removed_res.scalar_one_or_none()
        if removed_user and removed_user.role == UserRole.OWNER.value:
            removed_user.role = UserRole.CLIENT.value

        # Ensure developer (7089836188) and removed ID (8598163827) are never listed as barbers
        for non_barber_tg_id in (7089836188, 8598163827):
            u_res = await session.execute(select(User).where(User.telegram_id == non_barber_tg_id))
            u_obj = u_res.scalar_one_or_none()
            if u_obj:
                b_obj = await barber_repo.get_by_user_id(u_obj.id)
                if b_obj:
                    await barber_repo.delete_barber(b_obj.id)

        # 1. Deduplicate clients by 9-digit phone tail
        res = await session.execute(
            select(User)
            .where(User.role == UserRole.CLIENT.value, User.phone.is_not(None))
            .order_by(User.telegram_id.desc(), User.id.asc())
        )
        clients = list(res.scalars().all())
        by_tail: dict[str, User] = {}
        for cl in clients:
            digits = "".join(ch for ch in (cl.phone or "") if ch.isdigit())
            if len(digits) < 9:
                continue
            tail = digits[-9:]
            if tail not in by_tail:
                by_tail[tail] = cl
            else:
                primary = by_tail[tail]
                await session.execute(
                    update(Order).where(Order.client_id == cl.id).values(client_id=primary.id)
                )
                await session.execute(
                    update(Payment).where(Payment.client_id == cl.id).values(client_id=primary.id)
                )
                await session.execute(delete(User).where(User.id == cl.id))

        # 2. Link orphan walk-in orders with matching phone to the single User
        if by_tail:
            orphan_res = await session.execute(
                select(Order).where(Order.client_id.is_(None), Order.walkin_phone.is_not(None))
            )
            for ord_obj in orphan_res.scalars().all():
                odigits = "".join(ch for ch in (ord_obj.walkin_phone or "") if ch.isdigit())
                if len(odigits) >= 9 and odigits[-9:] in by_tail:
                    ord_obj.client_id = by_tail[odigits[-9:]].id

        # 3. Prune old junk records (never touches COMPLETED visits or paid orders)
        now = now_utc()
        paid_order_ids_subq = select(Payment.order_id).where(Payment.order_id.is_not(None))

        # Delete abandoned PENDING_PAYMENT older than 24h
        await session.execute(
            delete(Order).where(
                Order.status == OrderStatus.PENDING_PAYMENT.value,
                Order.created_at < now - timedelta(hours=24),
                Order.id.not_in(paid_order_ids_subq),
            )
        )
        # Delete old cancelled / no-show / expired orders older than 14 days
        await session.execute(
            delete(Order).where(
                Order.status.in_([
                    OrderStatus.CANCELLED_BY_CLIENT.value,
                    OrderStatus.CANCELLED_BY_STAFF.value,
                    OrderStatus.CANCELLED_NO_SHOW.value,
                    OrderStatus.EXPIRED.value,
                ]),
                Order.created_at < now - timedelta(days=14),
                Order.id.not_in(paid_order_ids_subq),
            )
        )
        # Delete old audit logs older than 30 days
        await session.execute(
            delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=30))
        )
        # Delete old processed updates older than 7 days
        await session.execute(
            delete(ProcessedUpdate).where(ProcessedUpdate.processed_at < now - timedelta(days=7))
        )
        # Delete expired barber invites older than 3 days
        await session.execute(
            delete(BarberInvite).where(BarberInvite.expires_at < now - timedelta(days=3))
        )
        await session.commit()


def setup_internal_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession] = async_session_maker,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)

    async def tick_job():
        try:
            notifier = NotificationService(bot=bot)
            await process_due_work(session_factory, notifier=notifier)
        except Exception as e:
            logger.error("Error during scheduled internal tick: %s", e)

    async def keep_alive_ping_job():
        try:
            await cleanup_database_bloat(session_factory)
        except Exception as e:
            logger.debug("DB cleanup warning: %s", e)

        base_url = (settings.SITE_BASE_URL or "").rstrip("/")
        if not base_url or "localhost" in base_url or "127.0.0.1" in base_url:
            return
        ping_url = f"{base_url}/login"
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(ping_url) as resp:
                    logger.info("Keep-alive ping to %s returned %s", ping_url, resp.status)
        except Exception as e:
            logger.debug("Keep-alive ping warning: %s", e)

    # Run queue due work every 15 seconds
    scheduler.add_job(tick_job, "interval", seconds=15, id="queue_due_work_tick")
    # Ping public URL & run DB deduplication/cleanup every 10 minutes
    scheduler.add_job(keep_alive_ping_job, "interval", minutes=10, id="render_keep_alive_ping")
    return scheduler


