from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from app.i18n import t

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot: Bot | None = None):
        self.bot = bot
        self.sent_events: list[dict[str, Any]] = []

    async def send_message(
        self,
        telegram_id: int,
        text: str,
        reply_markup: Any = None,
        parse_mode: str | None = None,
    ) -> bool:
        """Send message to a telegram user. If bot is None (e.g. in tests), record to sent_events."""
        if not self.bot:
            self.sent_events.append({
                "telegram_id": telegram_id,
                "text": text,
                "reply_markup": reply_markup,
            })
            return True

        for attempt in range(2):
            try:
                await self.bot.send_message(
                    chat_id=telegram_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                return True
            except TelegramRetryAfter as e:
                logger.warning(
                    "TelegramRetryAfter sending to %s: retry in %ss (attempt %d/2)",
                    telegram_id,
                    e.retry_after,
                    attempt + 1,
                )
                if attempt == 0:
                    await asyncio.sleep(min(e.retry_after, 10))
                    continue
                return False
            except TelegramForbiddenError:
                logger.warning("User %s blocked the bot (TelegramForbiddenError)", telegram_id)
                return False
            except TelegramBadRequest as e:
                logger.warning("TelegramBadRequest sending to %s: %s", telegram_id, e)
                return False
            except Exception as e:
                logger.error("Error sending notification to %s: %s", telegram_id, e)
                return False
        return False

    async def send_photo(
        self,
        telegram_id: int,
        file_id: str,
        caption: str,
        reply_markup: Any = None,
        parse_mode: str | None = None,
    ) -> bool:
        """Send a photo (by Telegram file_id). If bot is None (tests), record to sent_events."""
        if not self.bot:
            self.sent_events.append({
                "telegram_id": telegram_id,
                "text": caption,
                "photo": file_id,
                "reply_markup": reply_markup,
            })
            return True

        for attempt in range(2):
            try:
                await self.bot.send_photo(
                    chat_id=telegram_id,
                    photo=file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                return True
            except TelegramRetryAfter as e:
                logger.warning(
                    "TelegramRetryAfter sending photo to %s: retry in %ss (attempt %d/2)",
                    telegram_id,
                    e.retry_after,
                    attempt + 1,
                )
                if attempt == 0:
                    await asyncio.sleep(min(e.retry_after, 10))
                    continue
                return False
            except TelegramForbiddenError:
                logger.warning("User %s blocked the bot (TelegramForbiddenError)", telegram_id)
                return False
            except TelegramBadRequest as e:
                logger.warning("TelegramBadRequest sending photo to %s: %s", telegram_id, e)
                return False
            except Exception as e:
                logger.error("Error sending photo to %s: %s", telegram_id, e)
                return False
        return False

    async def notify_client_called(
        self,
        client_tg_id: int,
        client_lang: str,
        barber_name: str,
    ) -> bool:
        text = t("client.called", lang=client_lang, barber=barber_name)
        return await self.send_message(client_tg_id, text)

    async def notify_client_heads_up(
        self,
        client_tg_id: int,
        client_lang: str,
        ahead_count: int,
        barber_name: str,
    ) -> bool:
        text = t("client.heads_up", lang=client_lang, n=ahead_count, barber=barber_name)
        return await self.send_message(client_tg_id, text)

    async def notify_client_moved_back(
        self,
        client_tg_id: int,
        client_lang: str,
        new_pos: int,
        late_count: int,
    ) -> bool:
        key = "client.moved_back_2" if late_count >= 2 else "client.moved_back_1"
        text = t(key, lang=client_lang, pos=new_pos)
        return await self.send_message(client_tg_id, text)

    async def notify_client_cancelled_no_show(
        self,
        client_tg_id: int,
        client_lang: str,
    ) -> bool:
        text = t("client.cancelled_no_show", lang=client_lang)
        return await self.send_message(client_tg_id, text)

    async def notify_barber_new_client(
        self,
        barber_tg_id: int,
        barber_lang: str,
        nick: str,
        service: str,
        pos: int,
        order_id: int | None = None,
    ) -> bool:
        text = t("barber.new_client_alert", lang=barber_lang, nick=nick, service=service, pos=pos)
        return await self.send_message(barber_tg_id, text)

    async def notify_barber_payment(
        self,
        barber_tg_id: int,
        barber_lang: str,
        nick: str,
        amount_fmt: str,
        method: str,
    ) -> bool:
        text = t(
            "barber.payment_alert",
            lang=barber_lang,
            nick=nick,
            amount=amount_fmt,
            method=method,
        )
        return await self.send_message(barber_tg_id, text)
