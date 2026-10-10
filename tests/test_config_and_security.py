from __future__ import annotations

import hmac
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from app.config import Settings, settings
from app.web.server import create_web_app


@pytest.mark.asyncio
async def test_c4_health_endpoint_no_env_leak(session_factory):
    """C4 acceptance: /health does not leak environment name or 'production'."""
    bot = MagicMock()
    dp = MagicMock()
    app = create_web_app(bot, dp, session_factory=session_factory)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert "env" not in data
        assert data.get("status") == "ok"
        assert data.get("db") == "ok"
        text = await resp.text()
        assert "production" not in text.lower()
        assert "development" not in text.lower()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_c3_secrets_timing_attack_protection(session_factory, monkeypatch):
    """C3 acceptance: constant-time HMAC comparison on tick and webhook endpoints."""
    monkeypatch.setattr(settings, "CRON_SECRET", "super_secret_cron_token_32chars_long!")
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "super_secret_webhook_token_32chars!")
    monkeypatch.setattr(settings, "WEBHOOK_PATH_SECRET", "path_secret_123")

    bot = MagicMock()
    dp = MagicMock()
    dp.feed_update = AsyncMock()
    app = create_web_app(bot, dp, session_factory=session_factory)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        # Invalid cron secret
        resp = await client.post("/internal/tick", headers={"X-Cron-Secret": "wrong_secret"})
        assert resp.status == 401

        # Valid cron secret
        resp = await client.post(
            "/internal/tick",
            headers={"X-Cron-Secret": "super_secret_cron_token_32chars_long!"},
        )
        assert resp.status == 200

        # Invalid webhook secret
        resp = await client.post(
            f"/webhook/{settings.WEBHOOK_PATH_SECRET}",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"},
            json={"update_id": 9999},
        )
        assert resp.status == 403
    finally:
        await client.close()


def test_c2_sqlite_crash_in_production(monkeypatch):
    """C2 acceptance: SQLite is rejected when ENV is production."""
    from app.db.session import create_app_engine

    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite+aiosqlite:///prod.db")
    with pytest.raises(RuntimeError) as exc_info:
        create_app_engine()
    assert "strictly prohibited" in str(exc_info.value).lower()
