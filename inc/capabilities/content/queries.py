"""Content queries.

Contract source: context/spec/capabilities/content.md §7/§8.

Public listing returns only published content; backend lists select status
at the API layer under permission. Ordering is fixed per spec: pinned
first (rank desc), then published_at desc nulls last, then id desc. total
uses the same filter and includes pinned items.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from inc.capabilities.content.dto import to_dto
from inc.capabilities.content.models import Content, ContentReference
from inc.capabilities.content.schemas import ContentDTO, ContentPageDTO, ReferenceDTO
from inc.capabilities.content.types import ContentTypeRegistry
from inc.kernel.db import Page, UoWFactory, fetch_page


class ContentQueries:
    """Read-only content surface."""

    def __init__(self, *, uow_factory: UoWFactory, types: ContentTypeRegistry) -> None:
        self._uow_factory = uow_factory
        self._types = types

    async def get(self, content_id: Any) -> ContentDTO | None:  # type: ignore[return]
        async with self._uow_factory() as uow:
            row: Content | None = await uow.session.get(Content, content_id)
            return self._to_dto(row) if row is not None else None

    async def list_contents(  # type: ignore[return]
        self,
        *,
        page: int,
        size: int,
        type_name: str | None = None,
        status: str | None = None,
        public_only: bool = False,
    ) -> ContentPageDTO:
        async with self._uow_factory() as uow:
            statement = select(Content)
            if public_only:
                statement = statement.where(Content.status == "published")
            elif status is not None:
                statement = statement.where(Content.status == status)
            if type_name is not None:
                statement = statement.where(Content.type_name == type_name)
            statement = statement.order_by(
                Content.is_pinned.desc(),
                Content.pin_rank.desc(),
                Content.published_at.desc().nullslast(),
                Content.id.desc(),
            )
            result: Page[Content] = await fetch_page(uow.session, statement, page=page, size=size)
            return ContentPageDTO(
                items=[self._to_dto(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )

    async def list_outgoing(self, content_id: Any) -> list[ReferenceDTO]:  # type: ignore[return]
        async with self._uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(ContentReference)
                        .where(ContentReference.source_content_id == content_id)
                        .order_by(ContentReference.position, ContentReference.id)
                    )
                )
                .scalars()
                .all()
            )
            return [self._ref_dto(row) for row in rows]

    async def list_incoming(self, content_id: Any) -> list[ReferenceDTO]:  # type: ignore[return]
        async with self._uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(ContentReference).where(
                            ContentReference.target_content_id == content_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            return [self._ref_dto(row) for row in rows]

    async def list_due_scheduled(self, *, now: Any, batch: int = 64) -> list[tuple[uuid.UUID, int]]:  # type: ignore[return]
        """Read-only probe of due scheduled content (for scanner/testing)."""

        async with self._uow_factory() as uow:
            rows = (
                await uow.session.execute(
                    select(Content.id, Content.schedule_version)
                    .where(Content.status == "scheduled", Content.publish_at <= now)
                    .order_by(Content.publish_at, Content.id)
                    .limit(batch)
                )
            ).all()
            return [(row[0], int(row[1])) for row in rows]

    def _to_dto(self, row: Content) -> ContentDTO:
        return to_dto(row)

    @staticmethod
    def _ref_dto(row: ContentReference) -> ReferenceDTO:
        return ReferenceDTO(
            id=str(row.id),
            target_content_id=str(row.target_content_id),
            kind=row.kind,
            position=row.position,
            metadata=dict(row.ref_metadata.model_dump()),
        )
