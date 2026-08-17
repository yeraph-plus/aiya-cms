"""Content admin router.

Contract source: context/spec/http-openapi.md, capabilities/content.md.

Content commands run with the principal's capability set; every write is
permission-checked by the capability itself. Query listing follows the
pin-stable ordering defined by the content spec.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.content.commands import (
    ArchiveContent,
    CommandContext,
    CreateContent,
    PublishContent,
    PurgeArchivedContent,
    RejectContent,
    ReplaceContentReferences,
    RestoreContentToDraft,
    ScheduleContent,
    SetContentPin,
    SubmitContent,
    UnscheduleContent,
    UpdateContent,
)
from inc.capabilities.content.schemas import (
    ContentDTO,
    ContentPageDTO,
    CreateContentInput,
    PurgeResultDTO,
    ReferenceDTO,
    ReplaceReferencesInput,
    ScheduleContentInput,
    SetContentPinInput,
    UpdateContentInput,
)
from inc.capabilities.engagement.schemas import EngagementSummaryDTO


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


def _ctx(ctx: AppContext, services: Services) -> CommandContext:
    return CommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        types=services.content_types,
        publication_policies=services.content_publication_policies,
        permissions=frozenset(ctx.principal.capabilities),
        actor_id=ctx.principal.subject_id,
        trace_id=ctx.trace_id,
    )


REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "content.read",
    "content.write",
    "content.schedule",
    "content.publish",
    "content.archive",
    "content.pin",
    "content.purge",
)

_ENGAGEMENT_SORT_FIELDS = {
    "view_count",
    "like_count",
    "rating_sum",
    "rating_count",
    "rating_average",
}


def _contains_engagement_sort(sort: str) -> bool:
    return any(part.strip().lstrip("-") in _ENGAGEMENT_SORT_FIELDS for part in sort.split(","))


async def _list_with_engagement_sort(
    services: Services,
    *,
    page: int,
    size: int,
    type_name: str | None,
    status: str | None,
    sort: str,
    public_only: bool = False,
    owner_id: uuid.UUID | str | None = None,
) -> ContentPageDTO:
    """Apply projection-owned ordering without crossing the ORM boundary."""

    engagement_queries = services.engagement_queries
    if engagement_queries is None:
        return await services.content_queries.list_contents(
            page=page,
            size=size,
            type_name=type_name,
            status=status,
            public_only=public_only,
            owner_id=owner_id,
        )
    fields = [part.strip().lstrip("-") for part in sort.split(",")]
    if not fields or any(field not in _ENGAGEMENT_SORT_FIELDS for field in fields):
        from inc.kernel.errors import ErrorCategory, KernelError

        raise KernelError(
            code="content.invalid_sort",
            category=ErrorCategory.VALIDATION,
            message="sort must contain only engagement fields",
        )
    ids, total = await engagement_queries.list_content_ids(
        page=page,
        size=size,
        type_name=type_name,
        status=status,
        public_only=public_only,
        sort=sort,
    )
    hydrated = await services.content_queries.get_many(ids)

    async def with_summary(content_id: uuid.UUID) -> Any:
        row = hydrated.get(str(content_id))
        if row is None:
            return None
        summary = await engagement_queries.get_summary(content_id)
        return row.model_copy(
            update={"engagement": summary or EngagementSummaryDTO(content_id=str(content_id))}
        )

    items = [
        item
        for item in await asyncio.gather(*(with_summary(content_id) for content_id in ids))
        if item is not None
    ]
    return ContentPageDTO(items=items, total=total, page=page, size=size)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "admin-content"])

    @router.get("/content", response_model=ContentPageDTO)
    async def list_content(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        type_name: str | None = None,
        status: str | None = None,
        sort: str | None = Query(default=None, max_length=200),
        ctx: AppContext = Depends(require_capability("content.read")),
    ) -> ContentPageDTO:
        owner_id = (
            None if "content.manage" in ctx.principal.capabilities else ctx.principal.subject_id
        )
        if sort and _contains_engagement_sort(sort):
            # The engagement projection only owns opaque content IDs and has
            # no owner predicate.  Never use it to page an author-scoped list;
            # fall back to the content query, which applies the owner filter
            # before hydration.
            if owner_id is not None:
                sort = None
            else:
                return await _list_with_engagement_sort(
                    services,
                    page=page,
                    size=size,
                    type_name=type_name,
                    status=status,
                    sort=sort,
                    owner_id=owner_id,
                )
        result = await services.content_queries.list_contents(
            page=page,
            size=size,
            type_name=type_name,
            status=status,
            sort=sort,
            owner_id=owner_id,
        )
        if services.engagement_queries is None:
            return result
        return result.model_copy(
            update={
                "items": [
                    item.model_copy(
                        update={
                            "engagement": await services.engagement_queries.get_summary(
                                uuid.UUID(item.id)
                            )
                        }
                    )
                    for item in result.items
                ]
            }
        )

    @router.get("/content/{content_id}", response_model=ContentDTO)
    async def get_content(
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.read")),
    ) -> ContentDTO:
        owner_id = (
            None if "content.manage" in ctx.principal.capabilities else ctx.principal.subject_id
        )
        content = await services.content_queries.get_for_owner(content_id, owner_id=owner_id)
        if content is None:
            from inc.kernel.errors import ErrorCategory, KernelError

            raise KernelError(
                code="content.not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"content {content_id}",
            )
        return content

    @router.get("/content/{content_id}/references", response_model=list[ReferenceDTO])
    async def list_references(
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.read")),
    ) -> list[ReferenceDTO]:
        return await services.content_queries.list_outgoing(content_id)

    @router.post("/content", response_model=ContentDTO)
    async def create_content(
        body: CreateContentInput,
        ctx: AppContext = Depends(require_capability("content.write")),
    ) -> ContentDTO:
        return await CreateContent(_ctx(ctx, services))(body)

    @router.patch("/content/{content_id}", response_model=ContentDTO)
    async def update_content(
        body: UpdateContentInput,
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.write")),
    ) -> ContentDTO:
        return await UpdateContent(_ctx(ctx, services))(content_id, body)

    @router.post("/content/{content_id}/submit", response_model=ContentDTO)
    async def submit_content(
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.write")),
    ) -> ContentDTO:
        return await SubmitContent(_ctx(ctx, services))(content_id)

    @router.post("/content/{content_id}/reject", response_model=ContentDTO)
    async def reject_content(
        body: RejectBody,
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.write")),
    ) -> ContentDTO:
        return await RejectContent(_ctx(ctx, services))(content_id, reason=body.reason)

    @router.post("/content/{content_id}/schedule", response_model=ContentDTO)
    async def schedule_content(
        body: ScheduleContentInput,
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.schedule")),
    ) -> ContentDTO:
        return await ScheduleContent(_ctx(ctx, services))(content_id, body.publish_at)

    @router.post("/content/{content_id}/unschedule", response_model=ContentDTO)
    async def unschedule_content(
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.schedule")),
    ) -> ContentDTO:
        return await UnscheduleContent(_ctx(ctx, services))(content_id)

    @router.post("/content/{content_id}/publish", response_model=ContentDTO)
    async def publish_content(
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.publish")),
    ) -> ContentDTO:
        return await PublishContent(_ctx(ctx, services))(content_id)

    @router.post("/content/{content_id}/archive", response_model=ContentDTO)
    async def archive_content(
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.archive")),
    ) -> ContentDTO:
        return await ArchiveContent(_ctx(ctx, services))(content_id)

    @router.post("/content/{content_id}/restore", response_model=ContentDTO)
    async def restore_content(
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.write")),
    ) -> ContentDTO:
        return await RestoreContentToDraft(_ctx(ctx, services))(content_id)

    @router.post("/content/{content_id}/pin", response_model=ContentDTO)
    async def set_pin(
        body: SetContentPinInput,
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.pin")),
    ) -> ContentDTO:
        return await SetContentPin(_ctx(ctx, services))(content_id, body)

    @router.put("/content/{content_id}/references", status_code=204)
    async def replace_references(
        body: ReplaceReferencesInput,
        content_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("content.write")),
    ) -> None:
        await ReplaceContentReferences(_ctx(ctx, services))(content_id, body)

    @router.post("/content/{content_id}/purge", response_model=PurgeResultDTO)
    async def purge_content(
        content_id: uuid.UUID = Path(...),
        dry_run: bool = Query(default=False),
        ctx: AppContext = Depends(require_capability("content.purge")),
    ) -> PurgeResultDTO:
        report = await PurgeArchivedContent(_ctx(ctx, services))(content_id, dry_run=dry_run)
        return PurgeResultDTO(**report)

    return router
