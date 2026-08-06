"""Read-only audit queries and append-only persistence repository."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select

from inc.kernel.db import Page, Repository

from .models import AuditLog


class AuditRepository(Repository[AuditLog]):
    model = AuditLog

    async def list_filtered(
        self,
        *,
        action: str | None = None,
        actor_id: UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[AuditLog]:
        filters = []
        if action is not None:
            filters.append(AuditLog.action == action)
        if actor_id is not None:
            filters.append(AuditLog.actor_id == actor_id)
        if created_from is not None:
            filters.append(AuditLog.created_at >= created_from)
        if created_to is not None:
            filters.append(AuditLog.created_at <= created_to)
        count = int(
            await self.session.scalar(select(func.count()).select_from(AuditLog).where(*filters))
            or 0
        )
        rows = await self.session.scalars(
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(size)
            .offset((page - 1) * size)
        )
        return Page(items=list(rows.all()), total=count, page=page, size=size)

    async def purge_before(self, cutoff: datetime) -> int:
        result = await self.session.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        return int(getattr(result, "rowcount", 0) or 0)
