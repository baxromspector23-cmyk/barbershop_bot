from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.barber import Barber
from app.models.enums import UserRole
from app.models.invite import BarberInvite
from app.models.user import User
from app.repositories.audit_repo import AuditRepository
from app.repositories.barber_repo import BarberRepository
from app.repositories.user_repo import UserRepository
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_repo = UserRepository(session)
        self.barber_repo = BarberRepository(session)
        self.audit_repo = AuditRepository(session)

    async def resolve_user(
        self,
        telegram_id: int,
        first_name: str,
        last_name: str | None = None,
        username: str | None = None,
    ) -> tuple[User, bool]:
        """
        Loads or registers user, updates name/username on every interaction,
        and bootstraps OWNER role for IDs defined in settings.OWNER_TELEGRAM_IDS.
        """
        is_owner_config = telegram_id in settings.OWNER_TELEGRAM_IDS
        role = UserRole.OWNER.value if is_owner_config else UserRole.CLIENT.value

        user, created = await self.user_repo.get_or_create(
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            role=role,
        )

        # If user was already created but is listed in OWNER_TELEGRAM_IDS, ensure OWNER role
        if is_owner_config and user.role != UserRole.OWNER.value:
            await self.user_repo.set_role(user.id, UserRole.OWNER.value)
            user.role = UserRole.OWNER.value

        # Owner also works as a barber (has own queue): ensure barber profile exists
        if user.role == UserRole.OWNER.value:
            existing_barber = await self.barber_repo.get_by_user_id(user.id)
            if not existing_barber:
                full_name = f"{first_name} {last_name or ''}".strip()
                new_barber = await self.barber_repo.create_barber(
                    user_id=user.id,
                    display_name=full_name or "Katta Barber",
                )
                await self.barber_repo.create_service(new_barber.id, "Soch olish", 50000, 30)
                await self.barber_repo.create_service(new_barber.id, "Soqol tekislash", 30000, 20)
                logger.info("Created barber queue profile for Owner #%s", user.id)

        await self.session.flush()
        return user, created

    async def create_barber_invite(self, creator_user_id: int) -> tuple[BarberInvite, str]:
        """Generate a cryptographically secure 24-hour single-use invite token."""
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires_at = now_utc() + timedelta(hours=24)

        invite = BarberInvite(
            token_hash=token_hash,
            created_by=creator_user_id,
            expires_at=expires_at,
        )
        self.session.add(invite)
        await self.session.flush()

        await self.audit_repo.log(
            actor_user_id=creator_user_id,
            action="BARBER_INVITE_CREATED",
            entity="BarberInvite",
            entity_id=str(invite.id),
        )
        return invite, raw_token

    async def validate_barber_invite(self, raw_token: str) -> BarberInvite | None:
        token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        stmt = (
            select(BarberInvite)
            .where(
                BarberInvite.token_hash == token_hash,
                BarberInvite.used_at.is_(None),
                BarberInvite.expires_at > now_utc(),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def complete_barber_onboarding(
        self,
        invite_id: int,
        user: User,
        display_name: str,
        phone: str,
        photo_file_id: str | None = None,
    ) -> Barber:
        stmt = select(BarberInvite).where(BarberInvite.id == invite_id)
        res = await self.session.execute(stmt)
        invite = res.scalar_one_or_none()
        if not invite or invite.used_at is not None:
            raise ValueError("Invite token is invalid or already used")

        # Mark invite as used
        invite.used_at = now_utc()
        invite.used_by = user.id

        # Upgrade user role
        await self.user_repo.set_role(user.id, UserRole.BARBER.value)
        await self.user_repo.update_phone(user.id, phone)
        user.role = UserRole.BARBER.value
        user.phone = phone

        # Create barber profile
        barber = await self.barber_repo.create_barber(
            user_id=user.id,
            display_name=display_name,
            photo_file_id=photo_file_id,
        )
        await self.barber_repo.create_service(barber.id, "Soch olish", 50000, 30)
        await self.barber_repo.create_service(barber.id, "Soqol tekislash", 30000, 20)

        await self.audit_repo.log(
            actor_user_id=user.id,
            action="BARBER_ONBOARDED",
            entity="Barber",
            entity_id=str(barber.id),
            data={"display_name": display_name, "phone": phone},
        )
        return barber

    async def toggle_client_block(
        self, admin_user_id: int, query: str
    ) -> tuple[User, bool] | None:
        user = await self.user_repo.get_by_username_or_id(query)
        if not user:
            return None

        new_status = not user.is_blocked
        await self.user_repo.set_blocked(user.id, new_status)
        user.is_blocked = new_status

        await self.audit_repo.log(
            actor_user_id=admin_user_id,
            action="USER_BLOCKED" if new_status else "USER_UNBLOCKED",
            entity="User",
            entity_id=str(user.id),
        )
        return user, new_status
