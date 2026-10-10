from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

from app.config import settings
from app.db.session import async_session_maker
from app.handlers import setup_routers
from app.middlewares.db_session import DbSessionMiddleware
from app.middlewares.error_handler import GlobalErrorHandlerMiddleware
from app.middlewares.throttling import ThrottlingMiddleware
from app.middlewares.user_context import UserContextMiddleware
from app.scheduler.jobs import setup_internal_scheduler
from app.web.server import create_web_app

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("barbershop_bot")


def build_dispatcher() -> Dispatcher:
    if settings.REDIS_URL:
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            logger.info("Using Redis FSM storage: %s", settings.REDIS_URL)
            storage = RedisStorage.from_url(settings.REDIS_URL)
        except ImportError:
            logger.warning("redis package not found, falling back to Memory FSM storage")
            storage = MemoryStorage()
    else:
        logger.info("Using Memory FSM storage")
        storage = MemoryStorage()

    dp = Dispatcher(storage=storage)

    # Register Middlewares
    dp.update.middleware(GlobalErrorHandlerMiddleware())
    dp.update.middleware(ThrottlingMiddleware())
    dp.update.middleware(DbSessionMiddleware(async_session_maker))
    dp.update.middleware(UserContextMiddleware())

    # Include Routers
    dp.include_router(setup_routers())
    return dp


async def main():
    settings.validate_runtime()
    bot = Bot(token=settings.BOT_TOKEN)
    dp = build_dispatcher()

    scheduler = None
    if settings.INTERNAL_SCHEDULER:
        scheduler = setup_internal_scheduler(bot, async_session_maker)
        scheduler.start()
        logger.info("Internal 15-second scheduler started")

    if settings.RUN_MODE == "webhook":
        logger.info("Starting bot in WEBHOOK mode on %s:%s", settings.HOST, settings.PORT)
        app = create_web_app(bot, dp, async_session_maker)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=settings.HOST, port=settings.PORT)
        await site.start()

        # Keep server running
        try:
            await asyncio.Event().wait()
        finally:
            if scheduler:
                scheduler.shutdown()
            await runner.cleanup()
            await bot.session.close()
    else:
        logger.info("Starting bot in POLLING mode")
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            if scheduler:
                scheduler.shutdown()
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
