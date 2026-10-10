#!/usr/bin/env python3
"""
scripts/set_webhook.py
CLI tool to register, verify, or delete Telegram Webhook.

Usage:
  python scripts/set_webhook.py
  python scripts/set_webhook.py --delete
  python scripts/set_webhook.py --url https://yourdomain.com --drop-pending
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aiogram import Bot

from app.config import settings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main():
    parser = argparse.ArgumentParser(description="Configure Telegram Webhook for Barbershop Bot")
    parser.add_argument("--url", help="Webhook base URL (e.g. https://example.com)")
    parser.add_argument("--secret", help="Secret token for X-Telegram-Bot-Api-Secret-Token")
    parser.add_argument("--drop-pending", action="store_true", help="Drop pending updates on Telegram servers")
    parser.add_argument("--max-connections", type=int, default=40, help="Max connections (1-100)")
    parser.add_argument("--delete", action="store_true", help="Delete webhook and switch back to polling")
    parser.add_argument("--info-only", action="store_true", help="Only display current webhook information")
    args = parser.parse_args()

    bot_token = settings.BOT_TOKEN
    if not bot_token or bot_token == "123456:TEST_BOT_TOKEN":
        print("❌ Xatolik: .env faylida BOT_TOKEN ko'rsatilmagan!")
        sys.exit(1)

    bot = Bot(token=bot_token)
    try:
        if args.delete:
            print("🔄 Webhook o'chirilmoqda va polling rejimiga o'tilmoqda...")
            await bot.delete_webhook(drop_pending_updates=args.drop_pending)
            print("✅ Webhook muvaffaqiyatli o'chirildi.")
        elif not args.info_only:
            base_url = args.url or settings.WEBHOOK_BASE_URL
            if not base_url:
                print("❌ Xatolik: Webhook URL ko'rsatilmagan (--url parametri yoki WEBHOOK_BASE_URL env).")
                sys.exit(1)

            base_url = base_url.rstrip("/")
            full_webhook_url = f"{base_url}/webhook/{settings.WEBHOOK_PATH_SECRET}"
            secret_token = args.secret or settings.WEBHOOK_SECRET

            print("🔗 Webhook o'rnatilmoqda:")
            print(f"   URL: {full_webhook_url}")
            print(f"   Max Connections: {args.max_connections}")
            print(f"   Drop Pending Updates: {args.drop_pending}")

            await bot.set_webhook(
                url=full_webhook_url,
                secret_token=secret_token,
                max_connections=args.max_connections,
                drop_pending_updates=args.drop_pending,
                allowed_updates=["message", "callback_query", "pre_checkout_query"],
            )
            print("✅ Webhook muvaffaqiyatli o'rnatildi!")

        # Print Webhook Info
        print("\n🔍 Webhook holati tekshirilmoqda (getWebhookInfo):")
        info = await bot.get_webhook_info()
        not_set_msg = "(O'rnatilmagan / Polling rejimida)"
        print(f"   URL:                     {info.url or not_set_msg}")
        print(f"   Custom Certificate:      {info.has_custom_certificate}")
        print(f"   Pending Update Count:    {info.pending_update_count}")
        print(f"   Last Error Date:         {info.last_error_date}")
        print(f"   Last Error Message:      {info.last_error_message}")
        print(f"   Max Connections:         {info.max_connections}")
        print(f"   Allowed Updates:         {info.allowed_updates}")

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
