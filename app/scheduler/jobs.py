from __future__ import annotations

import logging

import aiohttp
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

    async def keep_alive_ping_job():
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
    # Ping public URL every 10 minutes to prevent 15-minute idle sleep on Render
    scheduler.add_job(keep_alive_ping_job, "interval", minutes=10, id="render_keep_alive_ping")
    return scheduler

