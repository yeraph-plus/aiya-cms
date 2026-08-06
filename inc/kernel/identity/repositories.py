"""Repositories for the identity aggregates (ADR-0017/0018)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, or_, select

from inc.kernel.db import Page, Repository

from .models import Identity, Organization, User


class UserRepository(Repository[User]):
    model = User

    async def get_by_username(self, username: str) -> User | None:
        return cast(
            User | None, await self.session.scalar(select(User).where(User.username == username))
        )

    async def get_by_email(self, email: str) -> User | None:
        return cast(User | None, await self.session.scalar(select(User).where(User.email == email)))

    async def list_by_ids(self, user_ids: Sequence[UUID]) -> list[User]:
        if not user_ids:
            return []
        result = await self.session.scalars(select(User).where(User.id.in_(user_ids)))
        return list(result.all())

    async def list_filtered(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        page: int = 1,
        size: int = 20,
        sort: str = "created_at",
        order: str = "desc",
    ) -> Page[User]:
        filters = []
        if q:
            pattern = _contains_pattern(q)
            filters.append(
                or_(
                    User.username.ilike(pattern, escape="\\"),
                    User.email.ilike(pattern, escape="\\"),
                    User.display_name.ilike(pattern, escape="\\"),
                )
            )
        if status is not None:
            filters.append(User.status == status)
        if created_from is not None:
            filters.append(User.created_at >= created_from)
        if created_to is not None:
            filters.append(User.created_at <= created_to)
        if updated_from is not None:
            filters.append(User.updated_at >= updated_from)
        if updated_to is not None:
            filters.append(User.updated_at <= updated_to)
        try:
            order_column = {
                "username": User.username,
                "email": User.email,
                "display_name": User.display_name,
                "status": User.status,
                "created_at": User.created_at,
                "updated_at": User.updated_at,
            }[sort]
        except KeyError as exc:
            raise ValueError(f"unsupported user sort: {sort}") from exc
        ordering = order_column.asc() if order == "asc" else order_column.desc()
        ordering = ordering.nulls_last()
        tie_breaker = User.id.asc() if order == "asc" else User.id.desc()
        total = int(
            await self.session.scalar(select(func.count()).select_from(User).where(*filters)) or 0
        )
        rows = await self.session.scalars(
            select(User)
            .where(*filters)
            .order_by(ordering, tie_breaker)
            .limit(size)
            .offset((page - 1) * size)
        )
        return Page(items=list(rows.all()), total=total, page=page, size=size)


def _contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class IdentityRepository(Repository[Identity]):
    model = Identity

    async def list_for_user(self, user_id: UUID) -> list[Identity]:
        result = await self.session.scalars(
            select(Identity).where(Identity.user_id == user_id).order_by(Identity.id)
        )
        return list(result.all())

    async def get_password_for_update(self, user_id: UUID) -> Identity | None:
        result = await self.session.scalars(
            select(Identity)
            .where(Identity.user_id == user_id, Identity.provider == "password")
            .with_for_update()
        )
        return result.first()


class OrganizationRepository(Repository[Organization]):
    model = Organization
