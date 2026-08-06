"""Interaction persistence queries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from inc.kernel.db import Page, Repository

from .models import Interaction


class InteractionRepository(Repository[Interaction]):
    model = Interaction

    async def get_for_update_by_identity(
        self, user_id: UUID, target_type: str, target_id: UUID, kind: str
    ) -> Interaction | None:
        result = await self.session.scalars(
            select(Interaction)
            .where(
                Interaction.user_id == user_id,
                Interaction.target_type == target_type,
                Interaction.target_id == target_id,
                Interaction.kind == kind,
            )
            .with_for_update()
        )
        return result.first()

    async def delete(self, item: Interaction) -> None:
        await self.session.delete(item)

    async def list_for_user(
        self, user_id: UUID, *, kind: str | None, page: int, size: int
    ) -> Page[Interaction]:
        filters = [Interaction.user_id == user_id]
        if kind is not None:
            filters.append(Interaction.kind == kind)
        total = int(
            await self.session.scalar(select(func.count()).select_from(Interaction).where(*filters))
            or 0
        )
        rows = await self.session.scalars(
            select(Interaction)
            .where(*filters)
            .order_by(Interaction.created_at.desc(), Interaction.id.desc())
            .limit(size)
            .offset((page - 1) * size)
        )
        return Page(items=list(rows.all()), total=total, page=page, size=size)
