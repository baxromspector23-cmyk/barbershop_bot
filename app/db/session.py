from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

logger = logging.getLogger(__name__)


def get_engine_args(url: str) -> dict:
    args = {
        "pool_pre_ping": True,
        "echo": False,
    }
    if url.startswith("postgresql") or "asyncpg" in url:
        args["connect_args"] = {
            "prepared_statement_cache_size": 0,
            "statement_cache_size": 0,
        }
        args["pool_size"] = 10
        args["max_overflow"] = 5
    elif "sqlite" in url:
        args["connect_args"] = {"check_same_thread": False}
    return args


def create_app_engine():
    url = os.environ.get("DATABASE_URL", settings.DATABASE_URL)
    try:
        return create_async_engine(url, **get_engine_args(url))
    except (ModuleNotFoundError, Exception) as e:
        logger.warning(
            "Could not initialize engine with %s (%s). Falling back to sqlite+aiosqlite.",
            url,
            e,
        )
        fallback_url = "sqlite+aiosqlite:///barbershop_dev.db"
        return create_async_engine(fallback_url, **get_engine_args(fallback_url))


engine = create_app_engine()

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
