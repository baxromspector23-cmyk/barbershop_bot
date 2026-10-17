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


def sanitize_db_url(url: str) -> str:
    try:
        from sqlalchemy.engine import make_url
        u = make_url(url)
        host_str = f":{u.port}" if u.port else ""
        return f"{u.drivername}://{u.host or 'localhost'}{host_str}"
    except Exception:
        return url.split("@")[-1] if "@" in url else url.split("://")[0]


def create_app_engine():
    url = os.environ.get("DATABASE_URL", settings.DATABASE_URL)
    safe_target = sanitize_db_url(url)
    is_sqlite = "sqlite" in url

    if settings.ENV == "production":
        if is_sqlite:
            logger.critical("SQLite is strictly prohibited in production! Target=%s", safe_target)
            raise RuntimeError("SQLite is strictly prohibited in production.")
        if not (url.startswith("postgresql+asyncpg://") or "asyncpg" in url):
            logger.critical("Production requires PostgreSQL with asyncpg! Target=%s", safe_target)
            raise RuntimeError(f"Invalid production DATABASE_URL dialect: {safe_target}")
        try:
            return create_async_engine(url, **get_engine_args(url))
        except Exception as e:
            logger.critical("Failed to connect to PostgreSQL in production: %s", e)
            raise RuntimeError(f"PostgreSQL connection failed in production: {e}") from e

    # In dev or test environments:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    try:
        return create_async_engine(url, **get_engine_args(url))
    except (ModuleNotFoundError, Exception) as e:
        if settings.ENV in ["dev", "test", "development"]:
            logger.info("Database driver or host unavailable for %s (%s). Using dev SQLite.", safe_target, e)
            dev_url = "sqlite+aiosqlite:///barbershop_dev.db"
            return create_async_engine(dev_url, **get_engine_args(dev_url))
        raise


engine = create_app_engine()

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
