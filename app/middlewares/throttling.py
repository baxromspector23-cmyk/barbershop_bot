from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit_seconds: float = 0.5):
        super().__init__()
        self.rate_limit_seconds = rate_limit_seconds
        self.last_user_time: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if not tg_user:
            return await handler(event, data)

        now = time.time()
        last_time = self.last_user_time.get(tg_user.id, 0.0)

        if now - last_time < self.rate_limit_seconds:
            # Drop flood update, but answer callback query so Telegram spinner clears
            callback_query = getattr(event, "callback_query", None) or (event if hasattr(event, "answer") else None)
            if callback_query and hasattr(callback_query, "answer"):
                try:
                    await callback_query.answer()
                except Exception:
                    pass
            return

        self.last_user_time[tg_user.id] = now
        # Cleanup old entries periodically if map grows too large
        if len(self.last_user_time) > 10000:
            cutoff = now - 60.0
            self.last_user_time = {
                uid: t for uid, t in self.last_user_time.items() if t > cutoff
            }

        return await handler(event, data)
