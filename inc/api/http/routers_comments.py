"""Public submission/read and administrator moderation for comments."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.api.http.projections import AdminContentRefDTO, AdminSubjectRefDTO
from inc.capabilities.comments.commands import (
    ApproveComment,
    CommandContext,
    DeleteComment,
    RejectComment,
    SubmitComment,
)
from inc.capabilities.comments.schemas import (
    CommentDTO,
    DeleteCommentInput,
    RejectCommentInput,
    SubmitCommentBody,
    SubmitCommentInput,
)
from inc.kernel.db import Page
from inc.kernel.errors import ErrorCategory, KernelError

REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "comments.read",
    "comments.moderate",
    "comments.delete",
)


class AdminCommentDTO(CommentDTO):
    """Comment response enriched for administrator moderation tables."""

    author: AdminSubjectRefDTO | None = None
    target: AdminContentRefDTO | None = None


async def _decorate_admin_comments(
    services: Services, page: Page[CommentDTO]
) -> Page[AdminCommentDTO]:
    author_ids = {item.author_id for item in page.items if item.author_type == "identity"}
    authors = await services.identity_queries.get_subjects(author_ids)
    content_ids: list[uuid.UUID] = []
    for item in page.items:
        try:
            content_ids.append(uuid.UUID(item.target_id))
        except (ValueError, AttributeError) as _exc:
            del _exc
            continue
    contents = await services.content_queries.get_many(content_ids)
    decorated: list[AdminCommentDTO] = []
    for item in page.items:
        subject = authors.get(item.author_id)
        author = (
            AdminSubjectRefDTO(
                subject_type=item.author_type,
                subject_id=item.author_id,
                username=subject.username,
                display_name=subject.display_name,
                avatar_asset_id=subject.avatar_asset_id,
            )
            if subject is not None
            else None
        )
        content = contents.get(item.target_id)
        target = (
            AdminContentRefDTO(
                target_type=item.target_type,
                target_id=item.target_id,
                type_name=content.type_name,
                title=content.title,
                slug=content.slug,
                status=content.status,
            )
            if content is not None
            else None
        )
        decorated.append(AdminCommentDTO(**item.model_dump(), author=author, target=target))
    return Page(items=decorated, total=page.total, page=page.page, size=page.size)


async def _decorate_admin_comment(services: Services, item: CommentDTO) -> AdminCommentDTO:
    page = await _decorate_admin_comments(
        services,
        Page(items=[item], total=1, page=1, size=1),
    )
    return page.items[0]


def _ctx(
    services: Services,
    request_ctx: AppContext,
    *,
    permissions: frozenset[str] | None = None,
) -> CommandContext:
    return CommandContext(
        uow_factory=request_ctx.uow_factory,
        clock=request_ctx.clock,
        outbox=services.outbox,
        target_exists=services.adapters["comments.target_exists"],
        permissions=permissions or frozenset(request_ctx.principal.capabilities),
        actor_id=request_ctx.principal.subject_id,
        trace_id=request_ctx.trace_id,
    )


def _not_found(comment_id: uuid.UUID) -> KernelError:
    return KernelError(
        code="comments.not_found",
        category=ErrorCategory.NOT_FOUND,
        message=f"comment {comment_id} was not found",
    )


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    queries = services.comments_queries
    if queries is None:
        raise RuntimeError("comments router requires comments capability services")

    router = APIRouter(prefix="/api/v1")

    @router.get(
        "/content/{target_type}/{target_id}/comments",
        response_model=Page[CommentDTO],
        tags=["comments"],
    )
    async def list_published(
        target_type: str = Path(..., min_length=1, max_length=64),
        target_id: str = Path(..., min_length=1, max_length=200),
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
    ) -> Page[CommentDTO]:
        return await queries.list_published(target_type, target_id, page=page, size=size)

    @router.post(
        "/content/{target_type}/{target_id}/comments",
        response_model=CommentDTO,
        tags=["comments"],
    )
    async def submit(
        body: SubmitCommentBody,
        target_type: str = Path(..., min_length=1, max_length=64),
        target_id: str = Path(..., min_length=1, max_length=200),
        ctx: AppContext = Depends(require_authenticated()),
    ) -> CommentDTO:
        return await SubmitComment(_ctx(services, ctx, permissions=frozenset({"comments.submit"})))(
            SubmitCommentInput(
                target_type=target_type,
                target_id=target_id,
                author_type="identity",
                author_id=ctx.principal.subject_id,
                parent_id=body.parent_id,
                body=body.body,
            )
        )

    @router.get(
        "/admin/comments",
        response_model=Page[AdminCommentDTO],
        tags=["admin", "admin-comments"],
    )
    async def list_admin(
        page: int = Query(default=1, ge=1),
        size: int = Query(default=20, ge=1, le=100),
        status: str | None = Query(default=None),
        target_type: str | None = Query(default=None),
        target_id: str | None = Query(default=None),
        author_id: str | None = Query(default=None),
        ctx: AppContext = Depends(require_capability("comments.read")),
    ) -> Page[AdminCommentDTO]:
        result = await queries.list_admin(
            page=page,
            size=size,
            status=status,
            target_type=target_type,
            target_id=target_id,
            author_id=author_id,
        )
        return await _decorate_admin_comments(services, result)

    @router.get(
        "/admin/comments/{comment_id}",
        response_model=AdminCommentDTO,
        tags=["admin", "admin-comments"],
    )
    async def get_admin(
        comment_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("comments.read")),
    ) -> AdminCommentDTO:
        found = await queries.get(comment_id)
        if found is None:
            raise _not_found(comment_id)
        return await _decorate_admin_comment(services, found)

    @router.post(
        "/admin/comments/{comment_id}/approve",
        response_model=AdminCommentDTO,
        tags=["admin", "admin-comments"],
    )
    async def approve(
        comment_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("comments.moderate")),
    ) -> AdminCommentDTO:
        return await _decorate_admin_comment(
            services, await ApproveComment(_ctx(services, ctx))(comment_id)
        )

    @router.post(
        "/admin/comments/{comment_id}/reject",
        response_model=AdminCommentDTO,
        tags=["admin", "admin-comments"],
    )
    async def reject(
        body: RejectCommentInput,
        comment_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("comments.moderate")),
    ) -> AdminCommentDTO:
        return await _decorate_admin_comment(
            services, await RejectComment(_ctx(services, ctx))(comment_id, body)
        )

    @router.post(
        "/admin/comments/{comment_id}/delete",
        response_model=AdminCommentDTO,
        tags=["admin", "admin-comments"],
    )
    async def delete(
        body: DeleteCommentInput,
        comment_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("comments.delete")),
    ) -> AdminCommentDTO:
        return await _decorate_admin_comment(
            services, await DeleteComment(_ctx(services, ctx))(comment_id, body)
        )

    return router
