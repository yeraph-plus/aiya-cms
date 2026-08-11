"""Comments capability contract tests."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.comments.commands import (
    ApproveComment,
    CommandContext,
    DeleteComment,
    RejectComment,
    SubmitComment,
)
from inc.capabilities.comments.events import COMMENT_EVENT_SCHEMAS
from inc.capabilities.comments.models import Comment
from inc.capabilities.comments.queries import CommentQueries
from inc.capabilities.comments.schemas import (
    DeleteCommentInput,
    RejectCommentInput,
    SubmitCommentInput,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxMessage, OutboxWriter

TARGET_ID = "11111111-1111-1111-1111-111111111111"


class FakeTargets:
    async def __call__(self, target_type: str, target_id: str) -> bool:
        return target_type == "post" and target_id == TARGET_ID


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in COMMENT_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    schema_registry: EventSchemaRegistry,
) -> CommandContext:
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        target_exists=FakeTargets(),
        permissions=frozenset({"comments.submit", "comments.moderate", "comments.delete"}),
        actor_id="moderator-1",
        trace_id="comments-test",
    )


@pytest.fixture
def queries(uow_factory: UoWFactory) -> CommentQueries:
    return CommentQueries(uow_factory=uow_factory)


async def _submit(ctx: CommandContext, *, parent_id: uuid.UUID | None = None) -> Any:
    return await SubmitComment(ctx)(
        SubmitCommentInput(
            target_type="post",
            target_id=TARGET_ID,
            author_type="identity",
            author_id="author-1",
            parent_id=parent_id,
            body="A useful comment",
        )
    )


async def test_submit_approve_reject_and_public_visibility(
    ctx: CommandContext,
    queries: CommentQueries,
) -> None:
    submitted = await _submit(ctx)
    assert submitted.status == "pending"
    assert (await queries.list_published("post", TARGET_ID, page=1, size=20)).total == 0

    approved = await ApproveComment(ctx)(uuid.UUID(submitted.id))
    assert approved.status == "published"
    public = await queries.list_published("post", TARGET_ID, page=1, size=20)
    assert public.total == 1
    assert public.items[0].body == "A useful comment"

    rejected = await RejectComment(ctx)(
        uuid.UUID(submitted.id), RejectCommentInput(reason="Policy violation")
    )
    assert rejected.status == "rejected"
    assert rejected.moderation_reason == "Policy violation"
    assert (await queries.list_published("post", TARGET_ID, page=1, size=20)).total == 0


async def test_parent_must_share_target_and_only_one_reply_level(
    ctx: CommandContext,
) -> None:
    parent = await _submit(ctx)
    reply = await _submit(ctx, parent_id=uuid.UUID(parent.id))
    with pytest.raises(KernelError) as excinfo:
        await _submit(ctx, parent_id=uuid.UUID(reply.id))
    assert excinfo.value.code == "comments.reply_depth_exceeded"


async def test_submit_rejects_missing_target(ctx: CommandContext) -> None:
    with pytest.raises(KernelError) as excinfo:
        await SubmitComment(ctx)(
            SubmitCommentInput(
                target_type="post",
                target_id=str(uuid.uuid4()),
                author_type="identity",
                author_id="author-1",
                body="Missing",
            )
        )
    assert excinfo.value.code == "comments.target_missing"


async def test_delete_is_terminal_idempotent_and_hides_body(
    ctx: CommandContext,
    uow_factory: UoWFactory,
) -> None:
    submitted = await _submit(ctx)
    deleted = await DeleteComment(ctx)(
        uuid.UUID(submitted.id), DeleteCommentInput(reason="author request")
    )
    assert deleted.status == "deleted"
    assert deleted.body is None
    again = await DeleteComment(ctx)(uuid.UUID(submitted.id), DeleteCommentInput())
    assert again.status == "deleted"

    async with uow_factory() as uow:
        row = await uow.session.get(Comment, uuid.UUID(submitted.id))
        messages = (await uow.session.execute(select(OutboxMessage))).scalars().all()
    assert row is not None and row.body == "A useful comment"
    keys = [message.envelope.event_key for message in messages]
    assert keys.count("comments.submitted.v1") == 1
    assert keys.count("comments.deleted.v1") == 1
    assert keys.count(AUDIT_EVENT_KEY) == 1
