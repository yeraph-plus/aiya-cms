"""Semantic comments commands."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from inc.capabilities.comments.events import COMMENT_EVENT_SCHEMAS
from inc.capabilities.comments.models import Comment
from inc.capabilities.comments.ports import TargetExistsPort
from inc.capabilities.comments.schemas import (
    CommentDTO,
    DeleteCommentInput,
    RejectCommentInput,
    SubmitCommentInput,
)
from inc.kernel.db import UnitOfWork, UoWFactory, new_uuid7
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    target_exists: TargetExistsPort
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None


def _error(code: str, category: ErrorCategory, message: str) -> KernelError:
    return KernelError(code=code, category=category, message=message)


def _require(ctx: CommandContext, permission: str) -> None:
    if permission not in ctx.permissions:
        raise _error("comments.forbidden", ErrorCategory.FORBIDDEN, f"requires {permission}")


def to_dto(row: Comment) -> CommentDTO:
    return CommentDTO(
        id=str(row.id),
        target_type=row.target_type,
        target_id=row.target_id,
        author_type=row.author_type,
        author_id=row.author_id,
        parent_id=str(row.parent_id) if row.parent_id else None,
        body=None if row.status == "deleted" else row.body,
        status=row.status,
        moderation_reason=row.moderation_reason,
        submitted_at=row.submitted_at,
        published_at=row.published_at,
        rejected_at=row.rejected_at,
        deleted_at=row.deleted_at,
        version=row.version,
    )


async def _emit(ctx: CommandContext, uow: UnitOfWork, key: str, row: Comment) -> None:
    payload = COMMENT_EVENT_SCHEMAS[key].model_validate(
        {
            "comment_id": str(row.id),
            "target_type": row.target_type,
            "target_id": row.target_id,
            "author_type": row.author_type,
            "author_id": row.author_id,
            "parent_id": str(row.parent_id) if row.parent_id else None,
            "status": row.status,
            "reason": row.moderation_reason,
        }
    )
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=new_uuid7(),
            event_key=key,
            occurred_at=ctx.clock.utc_now(),
            producer="comments",
            aggregate_type="comment",
            aggregate_id=str(row.id),
            trace_id=ctx.trace_id,
            payload=payload.model_dump(mode="json"),
        ),
    )


async def _audit(ctx: CommandContext, uow: UnitOfWork, action: str, row: Comment) -> None:
    now = ctx.clock.utc_now()
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=new_uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=now,
            producer="comments",
            aggregate_type="comment",
            aggregate_id=str(row.id),
            trace_id=ctx.trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": now.isoformat(),
                "actor_type": "user" if ctx.actor_id else None,
                "actor_id": ctx.actor_id,
                "target_type": "comment",
                "target_id": str(row.id),
                "trace_id": ctx.trace_id,
                "details": {
                    "comment_target_type": row.target_type,
                    "comment_target_id": row.target_id,
                    "reason": row.moderation_reason,
                },
            },
        ),
    )


async def _get_for_update(uow: UnitOfWork, comment_id: uuid.UUID) -> Comment:
    row: Comment | None = await uow.session.get(Comment, comment_id, with_for_update=True)
    if row is None:
        raise _error(
            "comments.not_found", ErrorCategory.NOT_FOUND, f"comment {comment_id} was not found"
        )
    return row


class SubmitComment:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, input_: SubmitCommentInput
    ) -> CommentDTO:
        ctx = self._ctx
        _require(ctx, "comments.submit")
        body = input_.body.strip()
        if not body:
            raise _error("comments.empty_body", ErrorCategory.VALIDATION, "comment body is empty")
        if not await ctx.target_exists(input_.target_type, input_.target_id):
            raise _error(
                "comments.target_missing",
                ErrorCategory.VALIDATION,
                f"target {input_.target_type}:{input_.target_id} does not exist",
            )
        async with ctx.uow_factory() as uow:
            if input_.parent_id is not None:
                parent = await _get_for_update(uow, input_.parent_id)
                if parent.target_type != input_.target_type or parent.target_id != input_.target_id:
                    raise _error(
                        "comments.parent_target_mismatch",
                        ErrorCategory.VALIDATION,
                        "parent comment belongs to a different target",
                    )
                if parent.parent_id is not None:
                    raise _error(
                        "comments.reply_depth_exceeded",
                        ErrorCategory.VALIDATION,
                        "comments support one reply level",
                    )
                if parent.status == "deleted":
                    raise _error(
                        "comments.parent_deleted",
                        ErrorCategory.CONFLICT,
                        "cannot reply to a deleted comment",
                    )
            row = Comment(
                target_type=input_.target_type,
                target_id=input_.target_id,
                author_type=input_.author_type,
                author_id=input_.author_id,
                parent_id=input_.parent_id,
                body=body,
                status="pending",
                submitted_at=ctx.clock.utc_now(),
            )
            uow.session.add(row)
            await uow.session.flush()
            await _emit(ctx, uow, "comments.submitted.v1", row)
            await uow.commit()
            return to_dto(row)


class ApproveComment:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, comment_id: uuid.UUID
    ) -> CommentDTO:
        ctx = self._ctx
        _require(ctx, "comments.moderate")
        async with ctx.uow_factory() as uow:
            row = await _get_for_update(uow, comment_id)
            if row.status == "published":
                return to_dto(row)
            if row.status == "deleted":
                raise _error(
                    "comments.deleted_terminal", ErrorCategory.CONFLICT, "deleted is terminal"
                )
            row.status = "published"
            row.published_at = ctx.clock.utc_now()
            row.rejected_at = None
            row.moderation_reason = None
            row.version += 1
            await _emit(ctx, uow, "comments.approved.v1", row)
            await _audit(ctx, uow, "comments.approve", row)
            await uow.commit()
            return to_dto(row)


class RejectComment:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, comment_id: uuid.UUID, input_: RejectCommentInput
    ) -> CommentDTO:
        ctx = self._ctx
        _require(ctx, "comments.moderate")
        reason = input_.reason.strip()
        if not reason:
            raise _error("comments.empty_reason", ErrorCategory.VALIDATION, "reason is empty")
        async with ctx.uow_factory() as uow:
            row = await _get_for_update(uow, comment_id)
            if row.status == "rejected":
                return to_dto(row)
            if row.status == "deleted":
                raise _error(
                    "comments.deleted_terminal", ErrorCategory.CONFLICT, "deleted is terminal"
                )
            row.status = "rejected"
            row.rejected_at = ctx.clock.utc_now()
            row.moderation_reason = reason
            row.version += 1
            await _emit(ctx, uow, "comments.rejected.v1", row)
            await _audit(ctx, uow, "comments.reject", row)
            await uow.commit()
            return to_dto(row)


class DeleteComment:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, comment_id: uuid.UUID, input_: DeleteCommentInput
    ) -> CommentDTO:
        ctx = self._ctx
        _require(ctx, "comments.delete")
        async with ctx.uow_factory() as uow:
            row = await _get_for_update(uow, comment_id)
            if row.status == "deleted":
                return to_dto(row)
            reason = input_.reason.strip() if input_.reason else None
            row.status = "deleted"
            row.deleted_at = ctx.clock.utc_now()
            row.moderation_reason = reason or row.moderation_reason
            row.version += 1
            await _emit(ctx, uow, "comments.deleted.v1", row)
            await _audit(ctx, uow, "comments.delete", row)
            await uow.commit()
            return to_dto(row)
