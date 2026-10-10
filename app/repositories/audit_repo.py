from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log(
        self,
        action: str,
        entity: str,
        actor_user_id: int | None = None,
        entity_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            data=data,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry
