from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n import t
from app.services.user_service import UserService

logger = logging.getLogger(__name__)


class UserContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        session: AsyncSession | None = data.get("session")

        if not tg_user or not session:
            return await handler(event, data)

        user_service = UserService(session)
        user, _ = await user_service.resolve_user(
            telegram_id=tg_user.id,
            first_name=tg_user.first_name or "",
            last_name=tg_user.last_name,
            username=tg_user.username,
        )

        # Check blocked user
        if user.is_blocked:
            blocked_msg = t("common.blocked_user", lang=user.language)
            if isinstance(event, Message):
                await event.answer(blocked_msg)
            elif isinstance(event, CallbackQuery):
                await event.answer(blocked_msg, show_alert=True)
            return

        # Inject context variables
        data["user"] = user
        data["lang"] = user.language
        data["role"] = user.role

        return await handler(event, data)
