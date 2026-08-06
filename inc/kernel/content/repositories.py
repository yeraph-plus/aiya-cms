"""Content kernel repositories."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, or_, select, update

from inc.kernel.db import Page, Repository

from .models import Content


class ContentRepository(Repository[Content]):
    model = Content

    async def get_by_type_slug(self, type_name: str, slug: str) -> Content | None:
        return cast(
            Content | None,
            await self.session.scalar(
                select(Content).where(Content.type == type_name, Content.slug == slug)
            ),
        )

    async def list_for_type(
        self,
        type_name: str,
        *,
        statuses: Sequence[str],
        content_ids: Sequence[UUID] | None = None,
        owner_id: UUID | None = None,
        page: int = 1,
        size: int = 20,
        sort: str = "created_at",
        order: str = "desc",
        q: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        published_from: datetime | None = None,
        published_to: datetime | None = None,
    ) -> Page[Content]:
        filters = [Content.type == type_name, Content.status.in_(statuses)]
        if content_ids is not None:
            filters.append(Content.id.in_(content_ids))
        if owner_id is not None:
            filters.append(Content.owner_id == owner_id)
        if q:
            pattern = _contains_pattern(q)
            filters.append(
                or_(
                    Content.title.ilike(pattern, escape="\\"),
                    Content.slug.ilike(pattern, escape="\\"),
                    Content.excerpt.ilike(pattern, escape="\\"),
                )
            )
        if created_from is not None:
            filters.append(Content.created_at >= created_from)
        if created_to is not None:
            filters.append(Content.created_at <= created_to)
        if updated_from is not None:
            filters.append(Content.updated_at >= updated_from)
        if updated_to is not None:
            filters.append(Content.updated_at <= updated_to)
        if published_from is not None:
            filters.append(Content.published_at >= published_from)
        if published_to is not None:
            filters.append(Content.published_at <= published_to)
        try:
            order_column = {
                "title": Content.title,
                "slug": Content.slug,
                "status": Content.status,
                "published_at": Content.published_at,
                "created_at": Content.created_at,
                "updated_at": Content.updated_at,
                "view_count": Content.view_count,
                "like_count": Content.like_count,
                "rating_sum": Content.rating_sum,
                "rating_count": Content.rating_count,
                "comment_count": Content.comment_count,
            }[sort]
        except KeyError as exc:
            raise ValueError(f"unsupported content sort: {sort}") from exc
        ordering = order_column.asc() if order == "asc" else order_column.desc()
        ordering = ordering.nulls_last()
        tie_breaker = Content.id.asc() if order == "asc" else Content.id.desc()
        total = int(
            await self.session.scalar(select(func.count()).select_from(Content).where(*filters))
            or 0
        )
        rows = await self.session.scalars(
            select(Content)
            .where(*filters)
            .order_by(ordering, tie_breaker)
            .limit(size)
            .offset((page - 1) * size)
        )
        return Page(items=list(rows.all()), total=total, page=page, size=size)

    async def increment_views(self, content_id: UUID) -> None:
        await self.session.execute(
            update(Content)
            .where(Content.id == content_id)
            .values(view_count=Content.view_count + 1)
        )

    async def apply_interaction_delta(
        self,
        content_id: UUID,
        *,
        like_delta: int = 0,
        rating_sum_delta: int = 0,
        rating_count_delta: int = 0,
    ) -> None:
        await self.session.execute(
            update(Content)
            .where(Content.id == content_id)
            .values(
                like_count=func.greatest(Content.like_count + like_delta, 0),
                rating_sum=func.greatest(Content.rating_sum + rating_sum_delta, 0),
                rating_count=func.greatest(Content.rating_count + rating_count_delta, 0),
            )
        )

    async def apply_comment_count_delta(
        self, content_id: UUID, delta: int, *, content_type: str | None = None
    ) -> None:
        filters = [Content.id == content_id]
        if content_type is not None:
            filters.append(Content.type == content_type)
        await self.session.execute(
            update(Content)
            .where(*filters)
            .values(comment_count=func.greatest(Content.comment_count + delta, 0))
        )

    async def list_ids_by_type(self) -> dict[str, list[UUID]]:
        rows = await self.session.execute(
            select(Content.type, Content.id).order_by(Content.type, Content.id)
        )
        result: dict[str, list[UUID]] = {}
        for content_type, content_id in rows.all():
            result.setdefault(content_type, []).append(content_id)
        return result

    async def set_comment_count(self, content_type: str, content_id: UUID, count: int) -> None:
        await self.session.execute(
            update(Content)
            .where(Content.type == content_type, Content.id == content_id)
            .values(comment_count=max(count, 0))
        )

    async def purge_trash_before(self, cutoff: datetime) -> list[Content]:
        rows = await self.session.scalars(
            select(Content).where(Content.status == "trash", Content.trashed_at <= cutoff)
        )
        items = list(rows.all())
        for item in items:
            await self.session.delete(item)
        return items


def _contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
