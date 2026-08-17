"""Community user and administrator HTTP surfaces."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Path, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.community.commands import (
    ApprovePost,
    ArchiveDiscussion,
    ArchiveTag,
    CommandContext,
    CreateDiscussion,
    CreateReply,
    CreateTag,
    DeletePost,
    HideDiscussion,
    HidePost,
    LockDiscussion,
    PublishDiscussion,
    PurgeArchivedDiscussions,
    RebuildCommunitySearch,
    ReorderTags,
    ReplaceDiscussionTags,
    RestoreDiscussion,
    RestoreTag,
    SubmitDiscussion,
    UnlockDiscussion,
    UpdateDiscussion,
    UpdatePost,
    UpdateTag,
)
from inc.capabilities.community.schemas import (
    CommunityDiagnosticsDTO,
    CommunityPageDTO,
    CreateDiscussionBody,
    CreateDiscussionInput,
    CreateReplyBody,
    CreateReplyInput,
    CreateTagInput,
    DiscussionDTO,
    PostDTO,
    PurgeArchivedDiscussionsInput,
    ReorderTagsInput,
    ReplaceDiscussionTagsInput,
    TagDTO,
    UpdateDiscussionInput,
    UpdatePostInput,
    UpdateTagInput,
)
from inc.kernel.errors import ErrorCategory, KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "community.discussions.create",
    "community.discussions.reply",
    "community.discussions.edit_own",
    "community.discussions.moderate",
    "community.discussions.lock",
    "community.discussions.archive",
    "community.posts.moderate",
    "community.tags.manage",
    "community.read_admin",
    "community.search.rebuild",
    "community.purge",
)


def _ctx(services: Services, request_ctx: AppContext) -> CommandContext:
    return CommandContext(
        uow_factory=request_ctx.uow_factory,
        clock=request_ctx.clock,
        outbox=services.outbox,
        templates=services.community_templates,
        author_port=services.adapters["community.author"],
        permissions=frozenset(request_ctx.principal.capabilities),
        actor_id=request_ctx.principal.subject_id,
        trace_id=request_ctx.trace_id,
    )


def _public_not_found(message: str = "published community object not found") -> KernelError:
    return KernelError(
        code="community.not_found", category=ErrorCategory.NOT_FOUND, message=message
    )


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    queries = services.community_queries
    if queries is None:
        raise RuntimeError("community router requires community capability services")
    router = APIRouter(prefix="/api/v1")

    @router.get(
        "/community/discussions",
        response_model=CommunityPageDTO[DiscussionDTO],
        tags=["discussions"],
    )
    async def list_discussions(
        q: str | None = Query(default=None, max_length=128),
        tag: str | None = Query(default=None, max_length=120),
        sort: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
    ) -> CommunityPageDTO[DiscussionDTO]:
        return await queries.list_discussions(page=page, size=size, q=q, tag=tag, sort=sort)

    @router.post(
        "/community/discussions",
        response_model=DiscussionDTO,
        tags=["discussions"],
    )
    async def create_discussion(
        body: CreateDiscussionBody,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> DiscussionDTO:
        return await CreateDiscussion(_ctx(services, ctx))(
            CreateDiscussionInput(
                **body.model_dump(),
                author_type="identity",
                author_id=ctx.principal.subject_id,
                idempotency_key=idempotency_key,
            )
        )

    @router.get(
        "/community/discussions/by-slug/{slug}",
        response_model=DiscussionDTO,
        tags=["discussions"],
    )
    async def get_discussion_by_slug(
        slug: str = Path(..., min_length=1, max_length=255),
    ) -> DiscussionDTO:
        found = await queries.get_published_by_slug(slug)
        if found is None:
            raise _public_not_found()
        return found

    @router.patch(
        "/community/discussions/{discussion_id}",
        response_model=DiscussionDTO,
        tags=["discussions"],
    )
    async def update_discussion(
        body: UpdateDiscussionInput,
        discussion_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> DiscussionDTO:
        return await UpdateDiscussion(_ctx(services, ctx))(discussion_id, body)

    @router.get(
        "/community/discussions/{discussion_id}/posts",
        response_model=CommunityPageDTO[PostDTO],
        tags=["discussions"],
    )
    async def list_posts(
        discussion_id: uuid.UUID = Path(...),
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
    ) -> CommunityPageDTO[PostDTO]:
        discussion = await queries.get_discussion(discussion_id)
        if discussion is None or discussion.status != "published":
            raise _public_not_found()
        return await queries.list_posts(discussion_id, page=page, size=size)

    @router.post(
        "/community/discussions/{discussion_id}/replies",
        response_model=PostDTO,
        tags=["discussions"],
    )
    async def create_reply(
        body: CreateReplyBody,
        discussion_id: uuid.UUID = Path(...),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> PostDTO:
        return await CreateReply(_ctx(services, ctx))(
            CreateReplyInput(
                discussion_id=discussion_id,
                body=body.body,
                data=body.data,
                author_type="identity",
                author_id=ctx.principal.subject_id,
                idempotency_key=idempotency_key,
            )
        )

    @router.patch(
        "/community/posts/{post_id}",
        response_model=PostDTO,
        tags=["discussions"],
    )
    async def update_post(
        body: UpdatePostInput,
        post_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> PostDTO:
        return await UpdatePost(_ctx(services, ctx))(post_id, body)

    @router.get("/community/tags", response_model=list[TagDTO], tags=["community-tags"])
    async def list_tags() -> list[TagDTO]:
        return await queries.list_tags()

    @router.get("/community/tags/by-slug/{slug}", response_model=TagDTO, tags=["community-tags"])
    async def get_tag(slug: str = Path(..., min_length=1, max_length=120)) -> TagDTO:
        found = await queries.get_tag_by_slug(slug)
        if found is None:
            raise _public_not_found("community tag not found")
        return found

    @router.get(
        "/admin/community/discussions",
        response_model=CommunityPageDTO[DiscussionDTO],
        tags=["admin", "admin-community"],
    )
    async def list_admin_discussions(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        status: str | None = Query(default=None),
        author_id: str | None = Query(default=None, max_length=200),
        ctx: AppContext = Depends(require_capability("community.read_admin")),
    ) -> CommunityPageDTO[DiscussionDTO]:
        return await queries.list_admin_discussions(
            page=page, size=size, status=status, author_id=author_id
        )

    @router.get(
        "/admin/community/discussions/{discussion_id}",
        response_model=DiscussionDTO,
        tags=["admin", "admin-community"],
    )
    async def get_admin_discussion(
        discussion_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.read_admin")),
    ) -> DiscussionDTO:
        found = await queries.get_discussion(discussion_id)
        if found is None:
            raise _public_not_found("community discussion not found")
        return found

    @router.get(
        "/admin/community/posts",
        response_model=CommunityPageDTO[PostDTO],
        tags=["admin", "admin-community"],
    )
    async def list_admin_posts(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        discussion_id: uuid.UUID | None = Query(default=None),
        status: str | None = Query(default=None),
        ctx: AppContext = Depends(require_capability("community.read_admin")),
    ) -> CommunityPageDTO[PostDTO]:
        return await queries.list_admin_posts(
            page=page, size=size, discussion_id=discussion_id, status=status
        )

    @router.post(
        "/admin/community/discussions/{discussion_id}/submit",
        response_model=DiscussionDTO,
        tags=["admin", "admin-community"],
    )
    async def submit_discussion(
        discussion_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.discussions.moderate")),
    ) -> DiscussionDTO:
        return await SubmitDiscussion(_ctx(services, ctx))(discussion_id)

    @router.post(
        "/admin/community/discussions/{discussion_id}/publish",
        response_model=DiscussionDTO,
        tags=["admin", "admin-community"],
    )
    async def publish_discussion(
        discussion_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.discussions.moderate")),
    ) -> DiscussionDTO:
        return await PublishDiscussion(_ctx(services, ctx))(discussion_id)

    @router.post(
        "/admin/community/discussions/{discussion_id}/hide",
        response_model=DiscussionDTO,
        tags=["admin", "admin-community"],
    )
    async def hide_discussion(
        discussion_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.discussions.moderate")),
    ) -> DiscussionDTO:
        return await HideDiscussion(_ctx(services, ctx))(discussion_id)

    @router.post(
        "/admin/community/discussions/{discussion_id}/restore",
        response_model=DiscussionDTO,
        tags=["admin", "admin-community"],
    )
    async def restore_discussion(
        discussion_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.discussions.moderate")),
    ) -> DiscussionDTO:
        return await RestoreDiscussion(_ctx(services, ctx))(discussion_id)

    @router.post(
        "/admin/community/discussions/{discussion_id}/archive",
        response_model=DiscussionDTO,
        tags=["admin", "admin-community"],
    )
    async def archive_discussion(
        discussion_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.discussions.archive")),
    ) -> DiscussionDTO:
        return await ArchiveDiscussion(_ctx(services, ctx))(discussion_id)

    @router.post(
        "/admin/community/discussions/{discussion_id}/lock",
        response_model=DiscussionDTO,
        tags=["admin", "admin-community"],
    )
    async def lock_discussion(
        discussion_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.discussions.lock")),
    ) -> DiscussionDTO:
        return await LockDiscussion(_ctx(services, ctx))(discussion_id)

    @router.post(
        "/admin/community/discussions/{discussion_id}/unlock",
        response_model=DiscussionDTO,
        tags=["admin", "admin-community"],
    )
    async def unlock_discussion(
        discussion_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.discussions.lock")),
    ) -> DiscussionDTO:
        return await UnlockDiscussion(_ctx(services, ctx))(discussion_id)

    @router.put(
        "/admin/community/discussions/{discussion_id}/tags",
        response_model=DiscussionDTO,
        tags=["admin", "admin-community"],
    )
    async def replace_tags(
        body: ReplaceDiscussionTagsInput,
        discussion_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.tags.manage")),
    ) -> DiscussionDTO:
        return await ReplaceDiscussionTags(_ctx(services, ctx))(discussion_id, body)

    @router.post(
        "/admin/community/posts/{post_id}/approve",
        response_model=PostDTO,
        tags=["admin", "admin-community"],
    )
    async def approve_post(
        post_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.posts.moderate")),
    ) -> PostDTO:
        return await ApprovePost(_ctx(services, ctx))(post_id)

    @router.post(
        "/admin/community/posts/{post_id}/hide",
        response_model=PostDTO,
        tags=["admin", "admin-community"],
    )
    async def hide_post(
        post_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.posts.moderate")),
    ) -> PostDTO:
        return await HidePost(_ctx(services, ctx))(post_id)

    @router.post(
        "/admin/community/posts/{post_id}/delete",
        response_model=PostDTO,
        tags=["admin", "admin-community"],
    )
    async def delete_post(
        post_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.posts.moderate")),
    ) -> PostDTO:
        return await DeletePost(_ctx(services, ctx))(post_id)

    @router.get(
        "/admin/community/tags", response_model=list[TagDTO], tags=["admin", "admin-community"]
    )
    async def list_admin_tags(
        include_archived: bool = Query(default=True),
        ctx: AppContext = Depends(require_capability("community.tags.manage")),
    ) -> list[TagDTO]:
        return await queries.list_tags(include_archived=include_archived)

    @router.post(
        "/admin/community/tags",
        response_model=TagDTO,
        tags=["admin", "admin-community"],
    )
    async def create_tag(
        body: CreateTagInput,
        ctx: AppContext = Depends(require_capability("community.tags.manage")),
    ) -> TagDTO:
        return await CreateTag(_ctx(services, ctx))(body)

    @router.patch(
        "/admin/community/tags/{tag_id}",
        response_model=TagDTO,
        tags=["admin", "admin-community"],
    )
    async def update_tag(
        body: UpdateTagInput,
        tag_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.tags.manage")),
    ) -> TagDTO:
        return await UpdateTag(_ctx(services, ctx))(tag_id, body)

    @router.post(
        "/admin/community/tags/{tag_id}/archive",
        response_model=TagDTO,
        tags=["admin", "admin-community"],
    )
    async def archive_tag(
        tag_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.tags.manage")),
    ) -> TagDTO:
        return await ArchiveTag(_ctx(services, ctx))(tag_id)

    @router.post(
        "/admin/community/tags/{tag_id}/restore",
        response_model=TagDTO,
        tags=["admin", "admin-community"],
    )
    async def restore_tag(
        tag_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("community.tags.manage")),
    ) -> TagDTO:
        return await RestoreTag(_ctx(services, ctx))(tag_id)

    @router.put(
        "/admin/community/tags/reorder",
        response_model=list[TagDTO],
        tags=["admin", "admin-community"],
    )
    async def reorder_tags(
        body: ReorderTagsInput,
        ctx: AppContext = Depends(require_capability("community.tags.manage")),
    ) -> list[TagDTO]:
        return await ReorderTags(_ctx(services, ctx))(body)

    @router.post(
        "/admin/community/search/rebuild",
        response_model=dict[str, Any],
        tags=["admin", "admin-community"],
    )
    async def rebuild_search(
        dry_run: bool = Query(default=False),
        ctx: AppContext = Depends(require_capability("community.search.rebuild")),
    ) -> dict[str, Any]:
        return await RebuildCommunitySearch(_ctx(services, ctx))(dry_run=dry_run)

    @router.get(
        "/admin/community/diagnostics",
        response_model=list[CommunityDiagnosticsDTO],
        tags=["admin", "admin-community"],
    )
    async def diagnostics(
        ctx: AppContext = Depends(require_capability("community.read_admin")),
    ) -> list[CommunityDiagnosticsDTO]:
        del ctx
        provider = services.community_diagnostics
        if provider is None:
            raise RuntimeError("community diagnostics are not available")
        return [
            CommunityDiagnosticsDTO(
                code=result.code, status=result.status.value, summary=result.summary
            )
            for result in await provider.run()
        ]

    @router.post(
        "/admin/community/discussions/purge",
        response_model=dict[str, Any],
        tags=["admin", "admin-community"],
    )
    async def purge_discussions(
        body: PurgeArchivedDiscussionsInput,
        ctx: AppContext = Depends(require_capability("community.purge")),
    ) -> dict[str, Any]:
        return await PurgeArchivedDiscussions(_ctx(services, ctx))(body)

    return router
