from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import time

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.barber import Barber, BarberWorkingHours
from app.models.enums import Language, UserRole
from app.models.service import Service
from app.models.user import User
from app.services.notification_service import NotificationService

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    kwargs = {"echo": False}
    if "sqlite" in TEST_DB_URL:
        kwargs["poolclass"] = StaticPool
        kwargs["connect_args"] = {"check_same_thread": False}
    elif "postgresql" in TEST_DB_URL or "asyncpg" in TEST_DB_URL:
        kwargs["connect_args"] = {"prepared_statement_cache_size": 0}

    engine = create_async_engine(TEST_DB_URL, **kwargs)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def session_factory(test_engine):
    return async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest_asyncio.fixture(scope="function")
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session


@pytest.fixture
def mock_notifier():
    return NotificationService(bot=None)


@pytest_asyncio.fixture(scope="function")
async def sample_barber(db_session: AsyncSession) -> Barber:
    session = db_session
    owner_user = User(
        telegram_id=111111,
        username="barber_bob",
        first_name="Bobur",
        last_name="Barber",
        language=Language.UZ.value,
        role=UserRole.BARBER.value,
    )
    session.add(owner_user)
    await session.flush()

    barber = Barber(
        user_id=owner_user.id,
        display_name="Bobur Barber",
        is_active=True,
        is_paused=False,
    )
    session.add(barber)
    await session.flush()

    for w in range(7):
        wh = BarberWorkingHours(
            barber_id=barber.id,
            weekday=w,
            start_time=time(0, 0),
            end_time=time(23, 59),
            is_day_off=False,
        )
        session.add(wh)

    svc1 = Service(
        barber_id=barber.id,
        name="Soch olish",
        price=50000,
        duration_minutes=30,
        is_active=True,
    )
    svc2 = Service(
        barber_id=barber.id,
        name="Soqol olish",
        price=30000,
        duration_minutes=20,
        is_active=True,
    )
    session.add_all([svc1, svc2])
    await session.commit()

    stmt = (
        select(Barber)
        .where(Barber.id == barber.id)
        .options(
            selectinload(Barber.working_hours),
            selectinload(Barber.services),
            selectinload(Barber.user),
        )
    )
    res = await session.execute(stmt)
    return res.scalar_one()


@pytest_asyncio.fixture(scope="function")
async def sample_clients(db_session: AsyncSession) -> list[User]:
    session = db_session
    clients = []
    for i in range(1, 6):
        c = User(
            telegram_id=200000 + i,
            username=f"client_{i}",
            first_name=f"Client{i}",
            language=Language.UZ.value,
            role=UserRole.CLIENT.value,
        )
        session.add(c)
        clients.append(c)
    await session.commit()

    stmt = select(User).where(User.telegram_id.in_([200000 + i for i in range(1, 6)])).order_by(User.id.asc())
    res = await session.execute(stmt)
    return list(res.scalars().all())
