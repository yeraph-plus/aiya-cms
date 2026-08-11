"""Public submission/read and administrator moderation for comments."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
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
        response_model=Page[CommentDTO],
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
    ) -> Page[CommentDTO]:
        return await queries.list_admin(
            page=page,
            size=size,
            status=status,
            target_type=target_type,
            target_id=target_id,
            author_id=author_id,
        )

    @router.get(
        "/admin/comments/{comment_id}",
        response_model=CommentDTO,
        tags=["admin", "admin-comments"],
    )
    async def get_admin(
        comment_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("comments.read")),
    ) -> CommentDTO:
        found = await queries.get(comment_id)
        if found is None:
            raise _not_found(comment_id)
        return found

    @router.post(
        "/admin/comments/{comment_id}/approve",
        response_model=CommentDTO,
        tags=["admin", "admin-comments"],
    )
    async def approve(
        comment_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("comments.moderate")),
    ) -> CommentDTO:
        return await ApproveComment(_ctx(services, ctx))(comment_id)

    @router.post(
        "/admin/comments/{comment_id}/reject",
        response_model=CommentDTO,
        tags=["admin", "admin-comments"],
    )
    async def reject(
        body: RejectCommentInput,
        comment_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("comments.moderate")),
    ) -> CommentDTO:
        return await RejectComment(_ctx(services, ctx))(comment_id, body)

    @router.post(
        "/admin/comments/{comment_id}/delete",
        response_model=CommentDTO,
        tags=["admin", "admin-comments"],
    )
    async def delete(
        body: DeleteCommentInput,
        comment_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("comments.delete")),
    ) -> CommentDTO:
        return await DeleteComment(_ctx(services, ctx))(comment_id, body)

    return router
