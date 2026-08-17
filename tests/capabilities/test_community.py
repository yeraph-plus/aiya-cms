"""Community capability contract tests."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.community.commands import (
    ApprovePost,
    ArchiveTag,
    CommandContext,
    CreateDiscussion,
    CreateReply,
    CreateTag,
    HidePost,
    LockDiscussion,
    PublishDiscussion,
    UpdateDiscussion,
    UpdateTag,
)
from inc.capabilities.community.diagnostics import CommunityDiagnostics
from inc.capabilities.community.events import COMMUNITY_EVENT_SCHEMAS
from inc.capabilities.community.markdown import validate_markdown
from inc.capabilities.community.models import (
    CommunityDiscussion,
    CommunityPost,
    CommunitySearchDocument,
)
from inc.capabilities.community.ports import CommunityAuthorPort
from inc.capabilities.community.queries import CommunityQueries
from inc.capabilities.community.schemas import (
    CommunityAuthorDTO,
    CreateDiscussionInput,
    CreateReplyInput,
    CreateTagInput,
    UpdateDiscussionInput,
    UpdateTagInput,
)
from inc.capabilities.community.search import SEARCH_PROFILE
from inc.capabilities.community.types import (
    GENERAL_DISCUSSION_TEMPLATE,
    DiscussionTemplateRegistry,
    DiscussionTemplateSpec,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxMessage, OutboxWriter


class FakeAuthors(CommunityAuthorPort):
    async def validate(self, author_type: str, author_id: str) -> bool:
        return author_type == "identity" and author_id.startswith("author-")

    async def project(self, references: Any) -> dict[tuple[str, str], CommunityAuthorDTO]:
        return {
            reference: CommunityAuthorDTO(id=reference[1], display_name=reference[1])
            for reference in references
        }


class ForumData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    safe: str
    secret: str


@pytest.fixture
def context(uow_factory: UoWFactory, clock: Any) -> CommandContext:
    templates = DiscussionTemplateRegistry()
    templates.register(GENERAL_DISCUSSION_TEMPLATE)
    registry = EventSchemaRegistry()
    for key, schema in COMMUNITY_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(registry, clock),
        templates=templates,
        author_port=FakeAuthors(),
        permissions=frozenset(
            {
                "community.discussions.create",
                "community.discussions.reply",
                "community.discussions.edit_own",
                "community.discussions.moderate",
                "community.discussions.lock",
                "community.discussions.archive",
                "community.posts.moderate",
                "community.tags.manage",
                "community.search.rebuild",
            }
        ),
        actor_id="author-1",
        trace_id="community-test",
    )


async def test_create_discussion_is_atomic_and_searchable(
    context: CommandContext, uow_factory: UoWFactory
) -> None:
    tag = await CreateTag(context)(CreateTagInput(kind="primary", name="Python", slug="python"))
    created = await CreateDiscussion(context)(
        CreateDiscussionInput(
            title="Python discussion",
            body="# Hello\r\n\r\nUseful text",
            tag_ids=[uuid.UUID(tag.id)],
            author_id="author-1",
            idempotency_key="create-1",
        )
    )
    assert created.status == "published"
    assert created.slug.startswith("python-discussion-")
    assert created.tags[0].slug == "python"
    assert created.first_post_id == created.last_post_id
    async with uow_factory() as uow:
        assert (await uow.session.execute(select(func.count(CommunityPost.id)))).scalar_one() == 1
        assert (
            await uow.session.execute(select(func.count(CommunitySearchDocument.id)))
        ).scalar_one() == 2
        messages = (await uow.session.execute(select(OutboxMessage))).scalars().all()
    assert any(
        message.envelope.event_key == "community.discussion_created.v1" for message in messages
    )


async def test_idempotency_replay_and_locked_reply(context: CommandContext) -> None:
    tag = await CreateTag(context)(CreateTagInput(kind="primary", name="General", slug="general"))
    input_ = CreateDiscussionInput(
        title="Replay me",
        body="Body",
        tag_ids=[uuid.UUID(tag.id)],
        author_id="author-1",
        idempotency_key="same-request",
    )
    first = await CreateDiscussion(context)(input_)
    replay = await CreateDiscussion(context)(input_)
    assert replay.id == first.id
    await LockDiscussion(context)(uuid.UUID(first.id))
    regular = context.__class__(
        uow_factory=context.uow_factory,
        clock=context.clock,
        outbox=context.outbox,
        templates=context.templates,
        author_port=context.author_port,
        permissions=context.permissions - {"community.discussions.moderate"},
        actor_id="author-2",
        trace_id=context.trace_id,
    )
    with pytest.raises(KernelError) as excinfo:
        await CreateReply(regular)(
            CreateReplyInput(
                discussion_id=uuid.UUID(first.id),
                body="reply",
                author_id="author-2",
                idempotency_key="reply-1",
            )
        )
    assert excinfo.value.code == "community.discussion_locked"


async def test_hidden_post_is_not_public_or_searchable(context: CommandContext) -> None:
    tag = await CreateTag(context)(CreateTagInput(kind="primary", name="Hidden", slug="hidden"))
    discussion = await CreateDiscussion(context)(
        CreateDiscussionInput(
            title="Hidden body",
            body="first body",
            tag_ids=[uuid.UUID(tag.id)],
            author_id="author-1",
        )
    )
    reply = await CreateReply(context)(
        CreateReplyInput(
            discussion_id=uuid.UUID(discussion.id), body="reply body", author_id="author-2"
        )
    )
    hidden = await HidePost(context)(uuid.UUID(reply.id))
    assert hidden.body is None
    queries = CommunityQueries(uow_factory=context.uow_factory, templates=context.templates)
    assert (await queries.list_posts(uuid.UUID(discussion.id), page=1, size=20)).total == 1
    assert (await queries.list_discussions(page=1, size=20, q="reply body")).total == 0


async def test_stale_hidden_search_document_is_not_publicly_searchable(
    context: CommandContext, clock: Any, uow_factory: UoWFactory
) -> None:
    tag = await CreateTag(context)(CreateTagInput(kind="primary", name="Stale", slug="stale"))
    discussion = await CreateDiscussion(context)(
        CreateDiscussionInput(
            title="Stale search",
            body="first body",
            tag_ids=[uuid.UUID(tag.id)],
            author_id="author-1",
        )
    )
    reply = await CreateReply(context)(
        CreateReplyInput(
            discussion_id=uuid.UUID(discussion.id), body="private phrase", author_id="author-2"
        )
    )
    await HidePost(context)(uuid.UUID(reply.id))
    async with uow_factory() as uow:
        uow.session.add(
            CommunitySearchDocument(
                id=uuid.uuid4(),
                discussion_id=uuid.UUID(discussion.id),
                post_id=uuid.UUID(reply.id),
                document_kind="post",
                search_profile=SEARCH_PROFILE,
                normalized_text="private phrase",
                source_version=1,
                created_at=clock.utc_now(),
                updated_at=clock.utc_now(),
            )
        )
        await uow.commit()
    queries = CommunityQueries(uow_factory=context.uow_factory, templates=context.templates)
    assert (await queries.list_discussions(page=1, size=20, q="private phrase")).total == 0


async def test_pending_post_can_be_approved(context: CommandContext) -> None:
    # A template with pending replies is a declaration-level policy, not a DB setting.
    pending_template = DiscussionTemplateSpec(
        template_key="general",
        version="1",
        display_name="General discussion",
        discussion_data_schema=GENERAL_DISCUSSION_TEMPLATE.discussion_data_schema,
        discussion_data_schema_version="1",
        post_data_schema=GENERAL_DISCUSSION_TEMPLATE.post_data_schema,
        post_data_schema_version="1",
        reply_moderation="pending",
    )
    pending_templates = DiscussionTemplateRegistry()
    pending_templates.register(pending_template)
    context = replace(context, templates=pending_templates)
    tag = await CreateTag(context)(CreateTagInput(kind="primary", name="Pending", slug="pending"))
    discussion = await CreateDiscussion(context)(
        CreateDiscussionInput(
            title="Pending reply",
            body="first",
            tag_ids=[uuid.UUID(tag.id)],
            author_id="author-1",
        )
    )
    reply = await CreateReply(context)(
        CreateReplyInput(
            discussion_id=uuid.UUID(discussion.id), body="pending", author_id="author-2"
        )
    )
    assert reply.status == "pending"
    approved = await ApprovePost(context)(uuid.UUID(reply.id))
    assert approved.status == "published"


def test_markdown_profile_rejects_unsafe_extensions_and_images() -> None:
    for body in (
        "<script>alert(1)</script>",
        "![image](https://example.com/x.png)",
        "[bad](javascript:alert(1))",
        "---\ntitle: no\n---\nbody",
    ):
        with pytest.raises(KernelError) as excinfo:
            validate_markdown(body, max_bytes=1000)
        assert excinfo.value.code == "community.markdown_invalid"


async def test_tag_hierarchy_and_archived_assignment_rules(context: CommandContext) -> None:
    root = await CreateTag(context)(CreateTagInput(kind="primary", name="Root", slug="root"))
    child = await CreateTag(context)(
        CreateTagInput(kind="primary", name="Child", slug="child", parent_id=uuid.UUID(root.id))
    )
    with pytest.raises(KernelError) as excinfo:
        await CreateTag(context)(
            CreateTagInput(
                kind="primary", name="Grandchild", slug="grandchild", parent_id=uuid.UUID(child.id)
            )
        )
    assert excinfo.value.code == "community.tag_hierarchy_invalid"
    with pytest.raises(KernelError) as excinfo:
        await CreateTag(context)(
            CreateTagInput(
                kind="secondary",
                name="Bad secondary",
                slug="bad-secondary",
                parent_id=uuid.UUID(root.id),
            )
        )
    assert excinfo.value.code == "community.tag_hierarchy_invalid"
    with pytest.raises(KernelError) as excinfo:
        await UpdateTag(context)(
            uuid.UUID(root.id),
            UpdateTagInput(expected_version=1, parent_id=uuid.UUID(root.id)),
        )
    assert excinfo.value.code == "community.tag_hierarchy_invalid"


async def test_custom_template_permissions_and_public_data_are_honored(
    context: CommandContext,
) -> None:
    template = DiscussionTemplateSpec(
        template_key="forum",
        version="1",
        display_name="Forum",
        discussion_data_schema=ForumData,
        discussion_data_schema_version="1",
        post_data_schema=ForumData,
        post_data_schema_version="1",
        create_access_key="forum.create",
        reply_access_key="forum.reply",
        edit_access_key="forum.edit",
        moderate_access_key="forum.moderate",
        lock_access_key="forum.lock",
        archive_access_key="forum.archive",
        tags_access_key="forum.tags",
        public_fields=("safe",),
    )
    templates = DiscussionTemplateRegistry()
    templates.register(template)
    context = replace(
        context,
        templates=templates,
        permissions=context.permissions
        | frozenset(
            {
                "forum.create",
                "forum.reply",
                "forum.edit",
                "forum.moderate",
                "forum.lock",
                "forum.archive",
                "forum.tags",
            }
        ),
    )
    tag = await CreateTag(context)(CreateTagInput(kind="primary", name="Forum", slug="forum"))
    discussion = await CreateDiscussion(context)(
        CreateDiscussionInput(
            template_key="forum",
            title="Forum post",
            body="body",
            data={"safe": "yes", "secret": "do-not-return"},
            post_data={"safe": "post", "secret": "post-secret"},
            tag_ids=[uuid.UUID(tag.id)],
            author_id="author-1",
        )
    )
    assert discussion.data == {"safe": "yes"}


async def test_author_type_is_part_of_own_edit_authorization(
    context: CommandContext, uow_factory: UoWFactory
) -> None:
    tag = await CreateTag(context)(CreateTagInput(kind="primary", name="Type", slug="type"))
    discussion = await CreateDiscussion(context)(
        CreateDiscussionInput(
            title="Opaque author",
            body="body",
            tag_ids=[uuid.UUID(tag.id)],
            author_id="author-1",
        )
    )
    async with uow_factory() as uow:
        row = await uow.session.get(CommunityDiscussion, uuid.UUID(discussion.id))
        assert row is not None
        row.author_type = "service"
        await uow.commit()
    regular = replace(
        context,
        permissions=context.permissions - {"community.discussions.moderate"},
    )
    with pytest.raises(KernelError) as excinfo:
        await UpdateDiscussion(regular)(
            uuid.UUID(discussion.id),
            UpdateDiscussionInput(expected_version=discussion.version, title="hijack"),
        )
    assert excinfo.value.code == "community.forbidden"


async def test_publish_discussion_is_idempotent(context: CommandContext) -> None:
    pending_template = DiscussionTemplateSpec(
        template_key="pending",
        version="1",
        display_name="Pending",
        discussion_data_schema=GENERAL_DISCUSSION_TEMPLATE.discussion_data_schema,
        discussion_data_schema_version="1",
        post_data_schema=GENERAL_DISCUSSION_TEMPLATE.post_data_schema,
        post_data_schema_version="1",
        discussion_moderation="pending",
        reply_moderation="pending",
    )
    templates = DiscussionTemplateRegistry()
    templates.register(pending_template)
    context = replace(context, templates=templates)
    tag = await CreateTag(context)(CreateTagInput(kind="primary", name="Publish", slug="publish"))
    discussion = await CreateDiscussion(context)(
        CreateDiscussionInput(
            template_key="pending",
            title="Pending publish",
            body="body",
            tag_ids=[uuid.UUID(tag.id)],
            author_id="author-1",
        )
    )
    first = await PublishDiscussion(context)(uuid.UUID(discussion.id))
    second = await PublishDiscussion(context)(uuid.UUID(discussion.id))
    assert second.version == first.version


async def test_diagnostics_accept_existing_assignment_to_archived_tag(
    context: CommandContext, clock: Any
) -> None:
    tag = await CreateTag(context)(CreateTagInput(kind="primary", name="History", slug="history"))
    discussion = await CreateDiscussion(context)(
        CreateDiscussionInput(
            title="Historical tag",
            body="body",
            tag_ids=[uuid.UUID(tag.id)],
            author_id="author-1",
        )
    )
    await ArchiveTag(context)(uuid.UUID(tag.id))
    diagnostics = CommunityDiagnostics(
        uow_factory=context.uow_factory,
        templates=context.templates,
        clock=clock,
        author_port=context.author_port,
    )
    results = {result.code: result.status.value for result in await diagnostics.run()}
    assert results["community.tag_assignment_invalid"] == "ok"
    assert results["community.orphan_author_reference"] == "ok"
    assert discussion.status == "published"
