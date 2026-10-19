import hmac
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db.session import async_session_maker
from app.models.processed_update import ProcessedUpdate
from app.services.due_work_service import process_due_work
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def create_web_app(
    bot: Bot,
    dp: Dispatcher,
    session_factory: async_sessionmaker[AsyncSession] = async_session_maker,
) -> web.Application:
    app = web.Application()

    async def health_handler(request: web.Request) -> web.Response:
        db_status = "ok"
        try:
            async with session_factory() as session:
                await session.execute(select(1))
        except Exception:
            db_status = "error"
        return web.json_response({"status": "ok", "db": db_status})

    async def tick_handler(request: web.Request) -> web.Response:
        cron_secret = request.headers.get("X-Cron-Secret", "")
        if not cron_secret or not hmac.compare_digest(cron_secret, settings.CRON_SECRET):
            return web.json_response({"error": "Unauthorized"}, status=401)

        notifier = NotificationService(bot=bot)
        results = await process_due_work(session_factory, notifier=notifier)
        return web.json_response({"status": "ok", "results": results})

    async def webhook_handler(request: web.Request) -> web.Response:
        secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secret_token or not hmac.compare_digest(secret_token, settings.WEBHOOK_SECRET):
            logger.warning("Rejected webhook: invalid secret token")
            return web.Response(status=403, text="Forbidden")

        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400, text="Bad Request")

        update_id = data.get("update_id")
        if update_id is not None:
            # Check idempotency: deduplicate update_id
            async with session_factory() as session:
                async with session.begin():
                    stmt = select(ProcessedUpdate).where(ProcessedUpdate.update_id == update_id)
                    res = await session.execute(stmt)
                    if res.scalar_one_or_none():
                        # Already processed: return 200 OK immediately
                        logger.debug("Duplicate update_id %s ignored", update_id)
                        return web.Response(status=200, text="OK")

                    session.add(ProcessedUpdate(update_id=update_id))

        try:
            update = Update.model_validate(data, context={"bot": bot})
            await dp.feed_update(bot=bot, update=update)
        except Exception as e:
            logger.exception("Error feeding webhook update: %s", e)

        return web.Response(status=200, text="OK")

    # Routes
    from app.site.webapp import handle_webapp_generate, handle_webapp_page

    app.router.add_get("/health", health_handler)
    app.router.add_post("/internal/tick", tick_handler)
    app.router.add_get("/webapp", handle_webapp_page)
    app.router.add_post("/webapp/api/generate", handle_webapp_generate)
    webhook_path = f"/webhook/{settings.WEBHOOK_PATH_SECRET}"
    app.router.add_post(webhook_path, webhook_handler)

    return app
