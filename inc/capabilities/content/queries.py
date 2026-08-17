"""Content queries.

Contract source: context/spec/capabilities/content.md §7/§8.

Public listing returns only published content; backend lists select status
at the API layer under permission. Default ordering is fixed per spec:
pinned first (rank desc), then published_at desc nulls last, then id desc.
An explicit ``sort`` (spec §7.1) overrides the default order and is
validated against the type's ``sort_options`` allowlist; the id DESC
stable key is always appended. total uses the same filter and includes
pinned items.
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
from inc.kernel.errors import ErrorCategory, KernelError

# Fixed column whitelist for explicit sort (spec §7.1): no expressions,
# no data-payload internals, no relationship fields.
_SORTABLE_COLUMNS: dict[str, Any] = {
    "id": Content.id,
    "title": Content.title,
    "slug": Content.slug,
    "published_at": Content.published_at,
    "created_at": Content.created_at,
    "updated_at": Content.updated_at,
    "pin_rank": Content.pin_rank,
}


def _invalid_sort(raw: str) -> KernelError:
    return KernelError(
        code="content.invalid_sort",
        category=ErrorCategory.VALIDATION,
        message=f"invalid sort field {raw!r}",
    )


class ContentQueries:
    """Read-only content surface."""

    def __init__(self, *, uow_factory: UoWFactory, types: ContentTypeRegistry) -> None:
        self._uow_factory = uow_factory
        self._types = types

    async def get(self, content_id: Any) -> ContentDTO | None:
        return await self.get_for_owner(content_id)

    async def get_for_owner(
        self, content_id: Any, *, owner_id: uuid.UUID | str | None = None
    ) -> ContentDTO | None:
        async with self._uow_factory() as uow:
            row: Content | None = await uow.session.get(Content, content_id)
            if owner_id is not None and (row is None or str(row.owner_id) != str(owner_id)):
                return None
            return self._to_dto(row) if row is not None else None
        raise RuntimeError("content owner query did not execute")

    async def get_published_by_slug(self, *, type_name: str, slug: str) -> ContentDTO | None:
        """Read one published item by its stable public route key."""

        self._types.require(type_name)
        async with self._uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(Content).where(
                            Content.type_name == type_name,
                            Content.slug == slug,
                            Content.status == "published",
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            return self._to_dto(row) if row is not None else None
        raise RuntimeError("content slug query did not execute")

    async def get_many(self, content_ids: list[Any]) -> dict[str, ContentDTO]:
        """Hydrate an ordered projection page without exposing ORM rows."""

        if not content_ids:
            return {}
        async with self._uow_factory() as uow:
            rows = (
                (await uow.session.execute(select(Content).where(Content.id.in_(content_ids))))
                .scalars()
                .all()
            )
            return {str(row.id): self._to_dto(row) for row in rows}
        raise RuntimeError("content batch query did not execute")

    async def list_contents(  # type: ignore[return]
        self,
        *,
        page: int,
        size: int,
        type_name: str | None = None,
        status: str | None = None,
        public_only: bool = False,
        sort: str | None = None,
        owner_id: uuid.UUID | str | None = None,
    ) -> ContentPageDTO:
        async with self._uow_factory() as uow:
            statement = select(Content)
            if public_only:
                statement = statement.where(Content.status == "published")
            elif status is not None:
                statement = statement.where(Content.status == status)
            if type_name is not None:
                statement = statement.where(Content.type_name == type_name)
            if owner_id is not None:
                statement = statement.where(Content.owner_id == uuid.UUID(str(owner_id)))
            orderings = self._resolve_sort(sort=sort, type_name=type_name)
            if orderings is None:
                statement = statement.order_by(
                    Content.is_pinned.desc(),
                    Content.pin_rank.desc(),
                    Content.published_at.desc().nullslast(),
                    Content.id.desc(),
                )
            else:
                statement = statement.order_by(*orderings)
            result: Page[Content] = await fetch_page(uow.session, statement, page=page, size=size)
            return ContentPageDTO(
                items=[self._to_dto(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )

    def _resolve_sort(self, *, sort: str | None, type_name: str | None) -> list[Any] | None:
        """Explicit sort (spec §7.1): type allowlist + stable id key."""

        if sort is None:
            return None
        if type_name is not None:
            spec = next((s for s in self._types.specs() if s.type_name == type_name), None)
            allowed = set(spec.sort_options) if spec is not None else set()
        else:
            # cross-type lists intersect every registered type's options
            intersection: set[str] | None = None
            for registered in self._types.specs():
                options = set(registered.sort_options)
                intersection = options if intersection is None else intersection & options
            allowed = intersection or set()
        orderings: list[Any] = []
        for raw in sort.split(","):
            field = raw.strip()
            descending = field.startswith("-")
            if descending:
                field = field[1:].strip()
            column = _SORTABLE_COLUMNS.get(field)
            if not field or field not in allowed or column is None:
                raise _invalid_sort(raw)
            orderings.append(
                column.desc().nulls_last() if descending else column.asc().nulls_first()
            )
        if not orderings:
            raise _invalid_sort(sort)
        orderings.append(Content.id.desc())
        return orderings

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
