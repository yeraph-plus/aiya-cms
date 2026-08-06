"""Comment kernel repositories."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select

from inc.kernel.db import Page, Repository

from .models import Comment


class CommentRepository(Repository[Comment]):
    model = Comment

    async def list_moderation(
        self,
        *,
        status: str | None = None,
        target_type: str | None = None,
        target_id: UUID | None = None,
        author_id: UUID | None = None,
        q: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        page: int = 1,
        size: int = 20,
        sort: str = "created_at",
        order: str = "desc",
    ) -> Page[Comment]:
        filters: list[Any] = []
        if status is not None:
            filters.append(Comment.status == status)
        if target_type is not None:
            filters.append(Comment.target_type == target_type)
        if target_id is not None:
            filters.append(Comment.target_id == target_id)
        if author_id is not None:
            filters.append(Comment.owner_id == author_id)
        if q:
            filters.append(Comment.content.ilike(_contains_pattern(q), escape="\\"))
        if created_from is not None:
            filters.append(Comment.created_at >= created_from)
        if created_to is not None:
            filters.append(Comment.created_at <= created_to)
        if updated_from is not None:
            filters.append(Comment.updated_at >= updated_from)
        if updated_to is not None:
            filters.append(Comment.updated_at <= updated_to)
        try:
            order_column = {
                "target_type": Comment.target_type,
                "status": Comment.status,
                "depth": Comment.depth,
                "created_at": Comment.created_at,
                "updated_at": Comment.updated_at,
            }[sort]
        except KeyError as exc:
            raise ValueError(f"unsupported comment sort: {sort}") from exc
        ordering = order_column.asc() if order == "asc" else order_column.desc()
        ordering = ordering.nulls_last()
        tie_breaker = Comment.id.asc() if order == "asc" else Comment.id.desc()
        total = int(
            await self.session.scalar(select(func.count()).select_from(Comment).where(*filters))
            or 0
        )
        rows = await self.session.scalars(
            select(Comment)
            .where(*filters)
            .order_by(ordering, tie_breaker)
            .limit(size)
            .offset((page - 1) * size)
        )
        return Page(items=list(rows.all()), total=total, page=page, size=size)

    async def count_roots(
        self,
        target_type: str,
        target_id: UUID,
        *,
        approved_only: bool,
        q: str | None = None,
    ) -> int:
        filters: list[Any] = [
            Comment.target_type == target_type,
            Comment.target_id == target_id,
            Comment.parent_id.is_(None),
        ]
        filters.extend(_approved_filters(approved_only))
        if q:
            filters.append(Comment.content.ilike(_contains_pattern(q), escape="\\"))
        return int(
            await self.session.scalar(select(func.count()).select_from(Comment).where(*filters))
            or 0
        )

    async def count_for_target(
        self, target_type: str, target_id: UUID, *, approved_only: bool
    ) -> int:
        filters: list[Any] = [
            Comment.target_type == target_type,
            Comment.target_id == target_id,
        ]
        filters.extend(_count_filters(approved_only))
        return int(
            await self.session.scalar(select(func.count()).select_from(Comment).where(*filters))
            or 0
        )

    async def list_roots(
        self,
        target_type: str,
        target_id: UUID,
        *,
        approved_only: bool,
        q: str | None = None,
        page: int,
        size: int,
        sort: str = "created_at",
        order: str = "asc",
    ) -> list[Comment]:
        filters: list[Any] = [
            Comment.target_type == target_type,
            Comment.target_id == target_id,
            Comment.parent_id.is_(None),
        ]
        filters.extend(_approved_filters(approved_only))
        if q:
            filters.append(Comment.content.ilike(_contains_pattern(q), escape="\\"))
        try:
            order_column = {"created_at": Comment.created_at, "updated_at": Comment.updated_at}[
                sort
            ]
        except KeyError as exc:
            raise ValueError(f"unsupported thread sort: {sort}") from exc
        ordering = order_column.asc() if order == "asc" else order_column.desc()
        ordering = ordering.nulls_last()
        tie_breaker = Comment.id.asc() if order == "asc" else Comment.id.desc()
        rows = await self.session.scalars(
            select(Comment)
            .where(*filters)
            .order_by(ordering, tie_breaker)
            .limit(size)
            .offset((page - 1) * size)
        )
        return list(rows.all())

    async def list_descendants(
        self, root_ids: Sequence[UUID], *, approved_only: bool
    ) -> list[Comment]:
        if not root_ids:
            return []
        filters: list[Any] = [Comment.root_id.in_(root_ids)]
        filters.extend(_approved_filters(approved_only))
        rows = await self.session.scalars(
            select(Comment).where(*filters).order_by(Comment.created_at, Comment.id)
        )
        return list(rows.all())

    async def has_children(self, comment_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(Comment.id).where(Comment.parent_id == comment_id).limit(1)
            )
        )

    async def mark_target_deleted(self, target_type: str, target_id: UUID) -> None:
        rows = await self.session.scalars(
            select(Comment).where(
                Comment.target_type == target_type, Comment.target_id == target_id
            )
        )
        for comment in rows.all():
            comment.content = "[deleted]"
            comment.data = comment.data.model_copy(update={"deleted": True})

    async def mark_pending_spam(self, owner_id: UUID) -> None:
        rows = await self.session.scalars(
            select(Comment).where(Comment.owner_id == owner_id, Comment.status == "pending")
        )
        for comment in rows.all():
            comment.status = "spam"

    async def purge_orphans_before(self, cutoff: datetime) -> int:
        filters = [
            Comment.updated_at < cutoff,
            or_(Comment.status == "spam", Comment.data["deleted"].as_boolean().is_(True)),
        ]
        rows = await self.session.scalars(select(Comment).where(*filters))
        items = list(rows.all())
        for item in items:
            await self.session.delete(item)
        return len(items)

    async def purge_spam_before(self, cutoff: datetime) -> int:
        return await self.purge_orphans_before(cutoff)


def _approved_filters(approved_only: bool) -> list[Any]:
    if not approved_only:
        return []
    return [Comment.status == "approved"]


def _count_filters(approved_only: bool) -> list[Any]:
    filters = _approved_filters(approved_only)
    if approved_only:
        deleted = Comment.data["deleted"].as_boolean()
        filters.append(or_(deleted.is_(None), deleted.is_(False)))
    return filters


def _contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
