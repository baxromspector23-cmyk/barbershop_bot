from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.i18n import t
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)


class GlobalErrorHandlerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramForbiddenError:
            tg_user = data.get("event_from_user")
            session = data.get("session")
            if tg_user and session:
                logger.warning("User %s blocked bot", tg_user.id)
                repo = UserRepository(session)
                await repo.set_bot_blocked(tg_user.id, True)
                await session.commit()
            return
        except TelegramBadRequest as e:
            msg = str(e).lower()
            if "message is not modified" in msg or "query is too old" in msg:
                # Normal Telegram noise: ignore gracefully
                return
            logger.warning("TelegramBadRequest: %s", e)
            return
        except Exception as e:
            logger.exception("Unhandled error processing update: %s", e)
            lang = data.get("lang", "uz")
            err_text = t("common.error_generic", lang=lang)
            try:
                if isinstance(event, Message):
                    await event.answer(err_text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(err_text, show_alert=True)
            except Exception:
                pass
            return
