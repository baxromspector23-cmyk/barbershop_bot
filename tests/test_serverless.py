from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiohttp.test_utils import (
    TestClient,
    TestServer,
)

from app.config import settings
from app.models.processed_update import ProcessedUpdate
from app.web.server import create_web_app


@pytest.mark.asyncio
async def test_webhook_security_and_deduplication(session_factory):
    bot = Bot(token="123456:FAKE_TOKEN")
    dp = Dispatcher()

    app = create_web_app(bot, dp, session_factory=session_factory)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        webhook_path = f"/webhook/{settings.WEBHOOK_PATH_SECRET}"

        # 1. Missing secret token -> 403 Forbidden
        resp = await client.post(webhook_path, json={"update_id": 100})
        assert resp.status == 403

        # 2. Invalid secret token -> 403 Forbidden
        resp = await client.post(
            webhook_path,
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"},
            json={"update_id": 100},
        )
        assert resp.status == 403

        # 3. Valid secret token with update_id 100 -> 200 OK
        valid_headers = {"X-Telegram-Bot-Api-Secret-Token": settings.WEBHOOK_SECRET}
        resp = await client.post(
            webhook_path,
            headers=valid_headers,
            json={"update_id": 100},
        )
        assert resp.status == 200

        # 4. Duplicate update_id 100 -> 200 OK immediately without re-processing
        resp = await client.post(
            webhook_path,
            headers=valid_headers,
            json={"update_id": 100},
        )
        assert resp.status == 200

        # Verify DB has exactly one record for update_id 100
        async with session_factory() as session:
            from sqlalchemy import select
            stmt = select(ProcessedUpdate).where(ProcessedUpdate.update_id == 100)
            res = await session.execute(stmt)
            records = res.scalars().all()
            assert len(records) == 1

    finally:
        await client.close()
        await bot.session.close()


@pytest.mark.asyncio
async def test_cron_tick_security(session_factory):
    bot = Bot(token="123456:FAKE_TOKEN")
    dp = Dispatcher()

    app = create_web_app(bot, dp, session_factory=session_factory)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # 1. Missing X-Cron-Secret -> 401
        resp = await client.post("/internal/tick")
        assert resp.status == 401

        # 2. Wrong X-Cron-Secret -> 401
        resp = await client.post("/internal/tick", headers={"X-Cron-Secret": "invalid_secret"})
        assert resp.status == 401

        # 3. Valid X-Cron-Secret -> 200 OK
        resp = await client.post("/internal/tick", headers={"X-Cron-Secret": settings.CRON_SECRET})
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert "results" in data

        # 4. Health check -> 200 OK
        health_resp = await client.get("/health")
        assert health_resp.status == 200
        health_data = await health_resp.json()
        assert health_data["status"] == "ok"

    finally:
        await client.close()
        await bot.session.close()
