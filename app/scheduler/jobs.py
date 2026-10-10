from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db.session import async_session_maker
from app.services.due_work_service import process_due_work
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


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

    # Run every 15 seconds
    scheduler.add_job(tick_job, "interval", seconds=15, id="queue_due_work_tick")
    return scheduler
