from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Language, UserRole
from app.models.user import User
from app.utils.time_utils import now_utc


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        stmt = select(User).where(User.id == user_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_id: int,
        first_name: str,
        last_name: str | None = None,
        username: str | None = None,
        language: str = Language.UZ.value,
        role: str = UserRole.CLIENT.value,
    ) -> tuple[User, bool]:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            # Refresh username/first_name/last_name
            updated = False
            if user.username != username:
                user.username = username
                updated = True
            if user.first_name != first_name:
                user.first_name = first_name
                updated = True
            if user.last_name != last_name:
                user.last_name = last_name
                updated = True
            if updated:
                user.updated_at = now_utc()
            return user, False

        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language=language,
            role=role,
            is_blocked=False,
            bot_blocked=False,
        )
        self.session.add(user)
        await self.session.flush()
        return user, True

    async def update_language(self, user_id: int, language: str) -> None:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(language=language, updated_at=now_utc())
        )
        await self.session.execute(stmt)

    async def update_phone(self, user_id: int, phone: str) -> None:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(phone=phone, updated_at=now_utc())
        )
        await self.session.execute(stmt)

    async def set_blocked(self, user_id: int, is_blocked: bool) -> None:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(is_blocked=is_blocked, updated_at=now_utc())
        )
        await self.session.execute(stmt)

    async def set_bot_blocked(self, telegram_id: int, bot_blocked: bool) -> None:
        stmt = (
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(bot_blocked=bot_blocked, updated_at=now_utc())
        )
        await self.session.execute(stmt)

    async def set_role(self, user_id: int, role: str) -> None:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(role=role, updated_at=now_utc())
        )
        await self.session.execute(stmt)

    async def get_by_username_or_id(self, query: str) -> User | None:
        clean = query.strip()
        if clean.startswith("@"):
            clean = clean[1:]
            stmt = select(User).where(User.username == clean)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        if clean.isdigit():
            tg_id = int(clean)
            return await self.get_by_telegram_id(tg_id)
        stmt = select(User).where(User.username == clean)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()
