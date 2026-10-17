from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonCommands
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


async def setup_bot_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Botni ishga tushirish / Перезапустить"),
            BotCommand(command="menu", description="Boshqaruv menyusi / Главное меню"),
            BotCommand(command="admin", description="Katta barber sayt boshqaruvi"),
        ])
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Bot commands and menu button configured successfully")
    except Exception as exc:
        logger.warning("Failed to configure bot commands or menu button: %s", exc)


async def main():
    settings.validate_runtime()
    bot = Bot(token=settings.BOT_TOKEN)
    await setup_bot_commands(bot)
    dp = build_dispatcher()

    scheduler = None
    if settings.INTERNAL_SCHEDULER:
        scheduler = setup_internal_scheduler(bot, async_session_maker)
        scheduler.start()
        logger.info("Internal 15-second scheduler started")

    site_runner = None
    if settings.SITE_ENABLED:
        from app.site.app import create_site_app

        site_app = create_site_app(
            async_session_maker,
            username=settings.SITE_USERNAME,
            password_hash=settings.SITE_PASSWORD_HASH,
            secret=settings.SITE_SESSION_SECRET,
            secure_cookies=settings.SITE_SECURE_COOKIES,
            trust_proxy=settings.SITE_TRUST_PROXY,
        )
        site_runner = web.AppRunner(site_app)
        await site_runner.setup()
        owner_site = web.TCPSite(site_runner, host=settings.HOST, port=settings.SITE_PORT)
        await owner_site.start()
        logger.info("Owner-only website started on %s:%s", settings.HOST, settings.SITE_PORT)

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
            if site_runner:
                await site_runner.cleanup()
            await runner.cleanup()
            await bot.session.close()
    else:
        logger.info("Starting bot in POLLING mode")
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            if scheduler:
                scheduler.shutdown()
            if site_runner:
                await site_runner.cleanup()
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

