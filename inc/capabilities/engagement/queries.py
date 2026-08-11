"""Read-only engagement queries."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from inc.capabilities.engagement.commands import EngagementCommands
from inc.capabilities.engagement.models import ContentEngagementStats, ContentLike
from inc.capabilities.engagement.schemas import EngagementSummaryDTO, FavoriteDTO, FavoritePageDTO
from inc.kernel.db import UoWFactory, fetch_page


class EngagementQueries:
    def __init__(self, *, uow_factory: UoWFactory, commands: EngagementCommands) -> None:
        self._uow_factory = uow_factory
        self._commands = commands

    async def get_summary(
        self, content_id: uuid.UUID, *, subject_id: uuid.UUID | str | None = None
    ) -> EngagementSummaryDTO | None:
        async with self._uow_factory() as uow:
            stats = (
                (
                    await uow.session.execute(
                        select(ContentEngagementStats).where(
                            ContentEngagementStats.content_id == content_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if stats is None:
                return None
            return await self._commands._summary(uow, stats, subject_id=subject_id)
        raise RuntimeError("engagement summary query did not execute")

    async def list_favorites(
        self,
        subject_id: uuid.UUID | str,
        *,
        page: int = 1,
        size: int = 20,
        type_name: str | None = None,
    ) -> FavoritePageDTO:
        sid = str(subject_id)
        async with self._uow_factory() as uow:
            statement = (
                select(ContentLike, ContentEngagementStats)
                .join(
                    ContentEngagementStats,
                    ContentEngagementStats.content_id == ContentLike.content_id,
                )
                .where(
                    ContentLike.subject_type == "user",
                    ContentLike.subject_id == sid,
                    ContentLike.removed_at.is_(None),
                    ContentEngagementStats.content_status == "published",
                )
                .order_by(ContentLike.liked_at.desc(), ContentLike.content_id.desc())
            )
            if type_name is not None:
                statement = statement.where(ContentEngagementStats.type_name == type_name)
            rows = (await uow.session.execute(statement)).all()
            visible: list[tuple[ContentLike, ContentEngagementStats]] = []
            for like, stats in rows:
                target = await self._commands._content_reader.get(stats.content_id)
                if target is not None and target.status == "published":
                    visible.append((like, stats))
            start = (page - 1) * size
            items = [
                FavoriteDTO(
                    content_id=str(like.content_id),
                    type_name=stats.type_name,
                    liked_at=like.liked_at,
                    summary=await self._commands._summary(
                        uow, stats, subject_id=sid, subject_type="user"
                    ),
                )
                for like, stats in visible[start : start + size]
            ]
            return FavoritePageDTO(items=items, total=len(visible), page=page, size=size)
        raise RuntimeError("engagement favorites query did not execute")

    async def list_stats(
        self, *, page: int = 1, size: int = 20, sort: str = "-view_count"
    ) -> tuple[list[EngagementSummaryDTO], int]:
        columns: dict[str, Any] = {
            "view_count": ContentEngagementStats.view_count,
            "like_count": ContentEngagementStats.like_count,
            "rating_sum": ContentEngagementStats.rating_sum,
            "rating_count": ContentEngagementStats.rating_count,
            "rating_average": ContentEngagementStats.rating_average,
            "published_at": ContentEngagementStats.published_at,
        }
        field = sort[1:] if sort.startswith("-") else sort
        column = columns.get(field)
        if column is None:
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="engagement.invalid_sort",
                category=ErrorCategory.VALIDATION,
                message=f"invalid sort field {sort!r}",
            )
        ordering = column.desc().nulls_last() if sort.startswith("-") else column.asc().nulls_last()
        async with self._uow_factory() as uow:
            statement = select(ContentEngagementStats).order_by(
                ordering,
                ContentEngagementStats.published_at.desc().nulls_last(),
                ContentEngagementStats.content_id.desc(),
            )
            result = await fetch_page(uow.session, statement, page=page, size=size)
            return [await self._commands._summary(uow, row) for row in result.items], result.total
        raise RuntimeError("engagement stats query did not execute")

    async def list_content_ids(
        self,
        *,
        page: int,
        size: int,
        sort: str,
        type_name: str | None = None,
        status: str | None = None,
        public_only: bool = False,
    ) -> tuple[list[uuid.UUID], int]:
        """Page opaque content ids using only the engagement projection.

        Content hydration is deliberately performed by the content query
        capability after this method returns, so interaction ordering never
        reaches across the capability boundary.
        """

        columns = {
            "view_count": ContentEngagementStats.view_count,
            "like_count": ContentEngagementStats.like_count,
            "rating_sum": ContentEngagementStats.rating_sum,
            "rating_count": ContentEngagementStats.rating_count,
            "rating_average": ContentEngagementStats.rating_average,
        }
        orderings: list[Any] = []
        for raw in sort.split(","):
            token = raw.strip()
            descending = token.startswith("-")
            field = token[1:].strip() if descending else token
            column = columns.get(field)
            if column is None:
                from inc.kernel.errors import ErrorCategory, KernelError

                raise KernelError(
                    code="engagement.invalid_sort",
                    category=ErrorCategory.VALIDATION,
                    message=f"invalid sort field {raw!r}",
                )
            # A missing projection value is not a zero interaction and must
            # remain at the end for both directions.
            orderings.append((column.desc() if descending else column.asc()).nulls_last())
        orderings.extend(
            [
                ContentEngagementStats.published_at.desc().nulls_last(),
                ContentEngagementStats.content_id.desc(),
            ]
        )
        async with self._uow_factory() as uow:
            statement = select(ContentEngagementStats)
            if public_only:
                statement = statement.where(ContentEngagementStats.content_status == "published")
            elif status is not None:
                statement = statement.where(ContentEngagementStats.content_status == status)
            if type_name is not None:
                statement = statement.where(ContentEngagementStats.type_name == type_name)
            result = await fetch_page(
                uow.session, statement.order_by(*orderings), page=page, size=size
            )
            return [row.content_id for row in result.items], result.total
        raise RuntimeError("engagement content projection query did not execute")
