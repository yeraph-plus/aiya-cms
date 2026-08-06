"""RBAC-specific query primitives."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, or_, select

from inc.kernel.db import Page, Repository
from inc.kernel.identity.models import User

from .models import Permission, Role, role_permissions, user_roles


def _contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class RoleRepository(Repository[Role]):
    model = Role

    async def get_by_name(self, name: str) -> Role | None:
        return cast(Role | None, await self.session.scalar(select(Role).where(Role.name == name)))

    async def list_ordered(self) -> list[Role]:
        return list((await self.session.scalars(select(Role).order_by(Role.name))).all())


class PermissionRepository(Repository[Permission]):
    model = Permission

    async def get_by_alias(self, alias: str) -> Permission | None:
        return cast(
            Permission | None,
            await self.session.scalar(select(Permission).where(Permission.alias == alias)),
        )

    async def list_ordered(self) -> list[Permission]:
        rows = await self.session.scalars(select(Permission).order_by(Permission.alias))
        return list(rows.all())


class RBACQueries:
    """Queries that span the RBAC association tables."""

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        self.session = session

    async def role_names_for_user(self, user_id: UUID) -> frozenset[str]:
        result = await self.session.scalars(
            select(Role.name)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user_id)
        )
        return frozenset(result.all())

    async def capabilities_for_user(self, user_id: UUID) -> frozenset[str]:
        result = await self.session.scalars(
            select(Permission.alias)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .join(user_roles, user_roles.c.role_id == role_permissions.c.role_id)
            .where(user_roles.c.user_id == user_id)
        )
        return frozenset(result.all())

    async def assign_role(
        self, user_id: UUID, role_id: UUID, organization_id: UUID | None = None
    ) -> None:
        organization_filter = (
            user_roles.c.organization_id.is_(None)
            if organization_id is None
            else user_roles.c.organization_id == organization_id
        )
        exists = await self.session.scalar(
            select(user_roles.c.user_id).where(
                user_roles.c.user_id == user_id,
                user_roles.c.role_id == role_id,
                organization_filter,
            )
        )
        if exists is None:
            await self.session.execute(
                user_roles.insert().values(
                    user_id=user_id,
                    role_id=role_id,
                    organization_id=organization_id,
                )
            )

    async def replace_roles(self, user_id: UUID, role_ids: list[UUID]) -> None:
        await self.session.execute(
            delete(user_roles).where(
                user_roles.c.user_id == user_id, user_roles.c.organization_id.is_(None)
            )
        )
        if role_ids:
            await self.session.execute(
                user_roles.insert(),
                [
                    {"user_id": user_id, "role_id": role_id, "organization_id": None}
                    for role_id in role_ids
                ],
            )

    async def role_names_for_users(self, user_ids: list[UUID]) -> dict[UUID, frozenset[str]]:
        if not user_ids:
            return {}
        rows = await self.session.execute(
            select(user_roles.c.user_id, Role.name)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(user_roles.c.user_id.in_(user_ids))
        )
        result: dict[UUID, set[str]] = {}
        for user_id, role_name in rows.all():
            result.setdefault(user_id, set()).add(role_name)
        return {key: frozenset(value) for key, value in result.items()}

    async def list_users_filtered(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        role: str | None = None,
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

        statement = select(User).outerjoin(user_roles, user_roles.c.user_id == User.id)
        count_statement = (
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .outerjoin(user_roles, user_roles.c.user_id == User.id)
        )
        if role:
            statement = statement.join(Role, Role.id == user_roles.c.role_id)
            count_statement = count_statement.join(Role, Role.id == user_roles.c.role_id)
            filters.append(Role.name == role)
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
        total = int(await self.session.scalar(count_statement.where(*filters)) or 0)
        rows = await self.session.scalars(
            statement.where(*filters)
            .distinct()
            .order_by(ordering, tie_breaker)
            .limit(size)
            .offset((page - 1) * size)
        )
        return Page(items=list(rows.all()), total=total, page=page, size=size)

    async def permission_ids_for_role(self, role_id: UUID) -> set[UUID]:
        result = await self.session.scalars(
            select(role_permissions.c.permission_id).where(role_permissions.c.role_id == role_id)
        )
        return set(result.all())

    async def add_role_permissions(self, role_id: UUID, permission_ids: list[UUID]) -> None:
        if permission_ids:
            await self.session.execute(
                role_permissions.insert(),
                [
                    {"role_id": role_id, "permission_id": permission_id}
                    for permission_id in permission_ids
                ],
            )
