"""Content capability tests.

Contract source: context/spec/capabilities/content.md §11.

Covers type registry fail-fast, transition/data/permission/owner/version
validation, scheduled publish once under duplicate and concurrent scans,
cancellation invalidation, pin pagination stability and reference-aware
purge. Runs against SQLite with the kernel UoW/outbox/workflow code paths.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select

from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.content.commands import (
    PERMISSION_MANAGE,
    ArchiveContent,
    CommandContext,
    CreateContent,
    PublishContent,
    PurgeArchivedContent,
    ReplaceContentReferences,
    RestoreContentToDraft,
    ScheduleContent,
    SetContentPin,
    SubmitContent,
    UnscheduleContent,
    UpdateContent,
)
from inc.capabilities.content.diagnostics import ContentDiagnostics
from inc.capabilities.content.events import CONTENT_EVENT_SCHEMAS
from inc.capabilities.content.models import Content
from inc.capabilities.content.publish import (
    PUBLISH_WORKFLOW_KEY,
    ContentPublishScanner,
    ScheduledPublishActivity,
    register_publish_workflow,
)
from inc.capabilities.content.queries import ContentQueries
from inc.capabilities.content.schemas import (
    CreateContentInput,
    ReplaceReferencesInput,
    SetContentPinInput,
    UpdateContentInput,
)
from inc.capabilities.content.types import (
    DEFAULT_TRANSITIONS,
    STANDARD_STATES,
    ContentTypeRegistry,
    ContentTypeSpec,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxMessage, OutboxWriter
from inc.kernel.workflow import WorkflowRegistry, WorkflowRunner


class PostData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = None
    tags: list[str] = []


class PageData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str | None = None


def make_post_spec() -> ContentTypeSpec:
    return ContentTypeSpec(
        type_name="post",
        version="1",
        display_name="Post",
        data_schema=PostData,
        data_schema_version="1",
        allowed_states=STANDARD_STATES,
        default_state="draft",
        transitions=DEFAULT_TRANSITIONS,
        allows_schedule=True,
        allows_pin=True,
        allows_owner=True,
        allows_references=True,
    )


def make_page_spec() -> ContentTypeSpec:
    return ContentTypeSpec(
        type_name="page",
        version="1",
        display_name="Page",
        data_schema=PageData,
        data_schema_version="1",
        allowed_states=STANDARD_STATES,
        default_state="draft",
        transitions=DEFAULT_TRANSITIONS,
        allows_schedule=True,
        allows_pin=True,
        allows_owner=True,
        allows_references=False,
        allows_incoming_references=False,
    )


ALL_PERMISSIONS = frozenset(
    {
        "content.write",
        "content.schedule",
        "content.publish",
        "content.archive",
        "content.pin",
        "content.purge",
        "content.manage",
    }
)


@pytest.fixture
def types() -> ContentTypeRegistry:
    registry = ContentTypeRegistry()
    registry.register(make_post_spec())
    registry.register(make_page_spec())
    return registry


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in CONTENT_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    types: ContentTypeRegistry,
    schema_registry: EventSchemaRegistry,
) -> CommandContext:
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        types=types,
        permissions=ALL_PERMISSIONS,
        actor_id="actor-1",
        trace_id="trace-1",
    )


@pytest.fixture
def queries(uow_factory: UoWFactory, types: ContentTypeRegistry) -> ContentQueries:
    return ContentQueries(uow_factory=uow_factory, types=types)


async def create_post(
    ctx: CommandContext,
    *,
    title: str = "Hello",
    slug: str | None = None,
    owner_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
):
    return await CreateContent(ctx)(
        CreateContentInput(
            type_name="post",
            title=title,
            slug=slug or f"slug-{uuid.uuid4().hex[:8]}",
            data=data or {"summary": "sum"},
            owner_id=owner_id,
        )
    )


async def _outbox_count(uow_factory: UoWFactory, event_key: str) -> int:
    async with uow_factory() as uow:
        return (
            await uow.session.execute(
                select(func.count(OutboxMessage.id)).where(OutboxMessage.event_key == event_key)
            )
        ).scalar_one()


# --- registry fail-fast --------------------------------------------------


def test_type_registry_rejects_duplicate_types(types: ContentTypeRegistry) -> None:
    with pytest.raises(KernelError) as excinfo:
        types.register(make_post_spec())
    assert excinfo.value.code == "content.duplicate_type"


def test_type_spec_rejects_unknown_states_and_broken_transitions() -> None:
    with pytest.raises(ValueError, match="unknown states"):
        ContentTypeSpec(
            type_name="odd",
            version="1",
            display_name="Odd",
            data_schema=PostData,
            data_schema_version="1",
            allowed_states=("draft", "magic"),
            default_state="draft",
        )
    with pytest.raises(ValueError, match="unknown start/end"):
        ContentTypeSpec(
            type_name="odd",
            version="1",
            display_name="Odd",
            data_schema=PostData,
            data_schema_version="1",
            allowed_states=("draft", "published"),
            default_state="draft",
            transitions=(("draft", "magic"),),
        )
    with pytest.raises(ValueError, match="without an outgoing transition"):
        ContentTypeSpec(
            type_name="odd",
            version="1",
            display_name="Odd",
            data_schema=PostData,
            data_schema_version="1",
            allowed_states=("draft", "published"),
            default_state="draft",
            transitions=(("draft", "published"),),
        )
    with pytest.raises(ValueError, match="not in allowed_states"):
        ContentTypeSpec(
            type_name="odd",
            version="1",
            display_name="Odd",
            data_schema=PostData,
            data_schema_version="1",
            allowed_states=("draft", "published"),
            default_state="pending",
            transitions=(("draft", "published"), ("published", "draft")),
        )


def test_type_spec_requires_pydantic_schema() -> None:
    with pytest.raises(ValueError, match="Pydantic data schema"):
        ContentTypeSpec(
            type_name="odd",
            version="1",
            display_name="Odd",
            data_schema=dict,  # type: ignore[arg-type]
            data_schema_version="1",
            allowed_states=("draft",),
            default_state="draft",
            transitions=(("draft", "draft"),),
        )


# --- create / update -----------------------------------------------------


async def test_create_requires_registered_type(ctx: CommandContext) -> None:
    with pytest.raises(KernelError) as excinfo:
        await CreateContent(ctx)(CreateContentInput(type_name="ghost", title="x", slug="ghost-1"))
    assert excinfo.value.code == "content.unknown_type"


async def test_create_validates_data_schema(ctx: CommandContext) -> None:
    with pytest.raises(ValidationError):
        await CreateContent(ctx)(
            CreateContentInput(type_name="post", title="x", slug="bad-data", data={"bogus": 1})
        )


async def test_create_requires_permission(
    uow_factory: UoWFactory,
    clock: Any,
    types: ContentTypeRegistry,
    schema_registry: EventSchemaRegistry,
) -> None:
    restricted = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        types=types,
        permissions=frozenset(),
    )
    with pytest.raises(KernelError) as excinfo:
        await CreateContent(restricted)(
            CreateContentInput(type_name="post", title="x", slug="nope")
        )
    assert excinfo.value.code == "content.forbidden"


async def test_create_duplicate_slug_conflicts(ctx: CommandContext) -> None:
    await create_post(ctx, slug="same")
    with pytest.raises(KernelError) as excinfo:
        await create_post(ctx, slug="same")
    assert excinfo.value.code == "content.duplicate_slug"


async def test_create_event_and_audit_carry_real_content_id(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    created = await create_post(ctx)
    async with uow_factory() as uow:
        rows = (
            (
                await uow.session.execute(
                    select(OutboxMessage).where(OutboxMessage.event_key == "content.created.v1")
                )
            )
            .scalars()
            .all()
        )
        audits = (
            (
                await uow.session.execute(
                    select(OutboxMessage).where(OutboxMessage.event_key == AUDIT_EVENT_KEY)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    payload = rows[0].envelope.payload
    assert payload["content_id"] == created.id
    assert rows[0].envelope.aggregate_id == created.id
    assert audits[-1].envelope.payload["target_id"] == created.id
    assert "None" not in str(payload)


async def test_update_lost_update_rejected_by_conditional_write(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    created = await create_post(ctx, title="v1")
    content_id = uuid.UUID(created.id)
    # simulate a concurrent writer bumping the version between read and write
    async with uow_factory() as uow:
        row = await uow.session.get(Content, content_id)
        assert row is not None
        row.version = 2
        await uow.commit()
    with pytest.raises(KernelError) as excinfo:
        await UpdateContent(ctx)(content_id, UpdateContentInput(expected_version=1, title="stale"))
    assert excinfo.value.code == "content.version_conflict"


async def test_update_optimistic_version_conflict(ctx: CommandContext) -> None:
    created = await create_post(ctx, title="v1")
    await UpdateContent(ctx)(
        uuid.UUID(created.id), UpdateContentInput(expected_version=1, title="v2")
    )
    with pytest.raises(KernelError) as excinfo:
        await UpdateContent(ctx)(
            uuid.UUID(created.id), UpdateContentInput(expected_version=1, title="stale")
        )
    assert excinfo.value.code == "content.version_conflict"
    updated = await UpdateContent(ctx)(
        uuid.UUID(created.id), UpdateContentInput(expected_version=2, title="v3")
    )
    assert updated.title == "v3" and updated.version == 3


async def test_update_without_changes_rejected(ctx: CommandContext) -> None:
    created = await create_post(ctx)
    with pytest.raises(KernelError) as excinfo:
        await UpdateContent(ctx)(uuid.UUID(created.id), UpdateContentInput(expected_version=1))
    assert excinfo.value.code == "content.empty_update"


# --- transitions ---------------------------------------------------------


async def test_transition_validation(ctx: CommandContext) -> None:
    created = await create_post(ctx)
    content_id = uuid.UUID(created.id)
    submitted = await SubmitContent(ctx)(content_id)
    assert submitted.status == "pending"
    with pytest.raises(KernelError) as excinfo:
        await SubmitContent(ctx)(content_id)
    assert excinfo.value.code == "content.invalid_transition"
    published = await PublishContent(ctx)(content_id)
    assert published.status == "published" and published.published_at is not None
    archived = await ArchiveContent(ctx)(content_id)
    assert archived.status == "archived" and archived.archived_at is not None
    restored = await RestoreContentToDraft(ctx)(content_id)
    assert restored.status == "draft"


async def test_publish_from_draft_allowed(ctx: CommandContext) -> None:
    created = await create_post(ctx)
    published = await PublishContent(ctx)(uuid.UUID(created.id))
    assert published.status == "published"


# --- scheduling ----------------------------------------------------------


async def test_schedule_requires_permission_and_future_time(
    ctx: CommandContext, clock: Any
) -> None:
    created = await create_post(ctx)
    content_id = uuid.UUID(created.id)
    no_perm = CommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=ctx.outbox,
        types=ctx.types,
        permissions=frozenset(),
    )
    with pytest.raises(KernelError) as excinfo:
        await ScheduleContent(no_perm)(content_id, clock.utc_now() + timedelta(hours=1))
    assert excinfo.value.code == "content.forbidden"
    with pytest.raises(KernelError) as excinfo:
        await ScheduleContent(ctx)(content_id, clock.utc_now() - timedelta(hours=1))
    assert excinfo.value.code == "content.schedule_in_past"
    naive = (clock.utc_now() + timedelta(hours=1)).replace(tzinfo=None)
    with pytest.raises(KernelError) as excinfo:
        await ScheduleContent(ctx)(content_id, naive)
    assert excinfo.value.code == "content.invalid_schedule"


async def test_unschedule_bumps_version_and_cancels(ctx: CommandContext, clock: Any) -> None:
    created = await create_post(ctx)
    content_id = uuid.UUID(created.id)
    scheduled = await ScheduleContent(ctx)(content_id, clock.utc_now() + timedelta(hours=1))
    assert scheduled.status == "scheduled" and scheduled.schedule_version == 1
    await UnscheduleContent(ctx)(content_id)
    rescheduled = await ScheduleContent(ctx)(content_id, clock.utc_now() + timedelta(hours=2))
    assert rescheduled.schedule_version == 3


# --- scheduled publish ---------------------------------------------------


@pytest.fixture
def publish_ctx(
    uow_factory: UoWFactory,
    clock: Any,
    types: ContentTypeRegistry,
    schema_registry: EventSchemaRegistry,
) -> tuple[WorkflowRunner, ContentPublishScanner, CommandContext]:
    outbox = OutboxWriter(schema_registry, clock)
    activity = ScheduledPublishActivity(clock=clock, outbox=outbox, actor_id="scanner")
    registry = WorkflowRegistry()
    register_publish_workflow(registry, activity=activity)
    runner = WorkflowRunner(uow_factory=uow_factory, registry=registry, clock=clock)
    scanner = ContentPublishScanner(uow_factory=uow_factory, clock=clock, runner=runner)
    cmd_ctx = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=outbox,
        types=types,
        permissions=ALL_PERMISSIONS,
    )
    return runner, scanner, cmd_ctx


async def test_scheduled_publish_fires_once(
    publish_ctx: tuple[WorkflowRunner, ContentPublishScanner, CommandContext],
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    runner, scanner, cmd_ctx = publish_ctx
    created = await create_post(cmd_ctx)
    content_id = uuid.UUID(created.id)
    await ScheduleContent(cmd_ctx)(content_id, clock.utc_now() + timedelta(minutes=5))

    clock.advance(timedelta(minutes=6))
    assert await scanner.scan_once() == 1
    assert await scanner.scan_once() == 0
    assert await runner.run_due(workflow_key=PUBLISH_WORKFLOW_KEY) == 1

    async with uow_factory() as uow:
        row: Content | None = await uow.session.get(Content, content_id)
        assert row is not None and row.status == "published"
        assert row.published_at is not None
    assert await _outbox_count(uow_factory, "content.published.v1") == 1
    assert await _outbox_count(uow_factory, "content.scheduled.v1") == 1
    assert await _outbox_count(uow_factory, AUDIT_EVENT_KEY) >= 1

    clock.advance(timedelta(days=1))
    assert await scanner.scan_once() == 0
    assert await _outbox_count(uow_factory, "content.published.v1") == 1


async def test_concurrent_scans_claim_once_then_publish_once(
    publish_ctx: tuple[WorkflowRunner, ContentPublishScanner, CommandContext],
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    runner, scanner, cmd_ctx = publish_ctx
    other = ContentPublishScanner(
        uow_factory=cmd_ctx.uow_factory,
        clock=clock,
        runner=runner,
        lease_owner="other-scanner",
    )
    created = await create_post(cmd_ctx)
    content_id = uuid.UUID(created.id)
    await ScheduleContent(cmd_ctx)(content_id, clock.utc_now() + timedelta(minutes=1))
    clock.advance(timedelta(minutes=2))

    claimed_first = await scanner.scan_once()
    claimed_second = await other.scan_once()
    assert claimed_first == 1
    assert claimed_second == 0
    await runner.run_due(workflow_key=PUBLISH_WORKFLOW_KEY)
    assert await _outbox_count(uow_factory, "content.published.v1") == 1
    assert await scanner.scan_once() == 0
    assert await _outbox_count(uow_factory, "content.published.v1") == 1


async def test_expired_lease_rescan_is_idempotent(
    publish_ctx: tuple[WorkflowRunner, ContentPublishScanner, CommandContext],
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    runner, scanner, cmd_ctx = publish_ctx
    created = await create_post(cmd_ctx)
    content_id = uuid.UUID(created.id)
    await ScheduleContent(cmd_ctx)(content_id, clock.utc_now() + timedelta(minutes=1))
    clock.advance(timedelta(minutes=2))
    assert await scanner.scan_once() == 1
    clock.advance(timedelta(hours=1))  # lease expires
    assert await scanner.scan_once() == 1  # re-claimed, same workflow instance
    assert await runner.run_due(workflow_key=PUBLISH_WORKFLOW_KEY) == 1
    assert await _outbox_count(uow_factory, "content.published.v1") == 1


async def test_cancelled_schedule_never_publishes(
    publish_ctx: tuple[WorkflowRunner, ContentPublishScanner, CommandContext],
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    runner, scanner, cmd_ctx = publish_ctx
    created = await create_post(cmd_ctx)
    content_id = uuid.UUID(created.id)
    await ScheduleContent(cmd_ctx)(content_id, clock.utc_now() + timedelta(minutes=5))
    clock.advance(timedelta(minutes=6))
    assert await scanner.scan_once() == 1
    await UnscheduleContent(cmd_ctx)(content_id)
    await runner.run_due(workflow_key=PUBLISH_WORKFLOW_KEY)
    async with uow_factory() as uow:
        row: Content | None = await uow.session.get(Content, content_id)
        assert row is not None and row.status == "draft"
    assert await _outbox_count(uow_factory, "content.published.v1") == 0
    assert await _outbox_count(uow_factory, "content.schedule_cancelled.v1") == 1


async def test_reschedule_makes_old_task_noop(
    publish_ctx: tuple[WorkflowRunner, ContentPublishScanner, CommandContext],
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    runner, scanner, cmd_ctx = publish_ctx
    created = await create_post(cmd_ctx)
    content_id = uuid.UUID(created.id)
    await ScheduleContent(cmd_ctx)(content_id, clock.utc_now() + timedelta(minutes=5))
    clock.advance(timedelta(minutes=6))
    assert await scanner.scan_once() == 1
    await UnscheduleContent(cmd_ctx)(content_id)
    await ScheduleContent(cmd_ctx)(content_id, clock.utc_now() + timedelta(minutes=30))
    await runner.run_due(workflow_key=PUBLISH_WORKFLOW_KEY)
    async with uow_factory() as uow:
        row: Content | None = await uow.session.get(Content, content_id)
        assert row is not None and row.status == "scheduled"
    clock.advance(timedelta(minutes=31))
    assert await scanner.scan_once() == 1
    await runner.run_due(workflow_key=PUBLISH_WORKFLOW_KEY)
    async with uow_factory() as uow:
        row2: Content | None = await uow.session.get(Content, content_id)
        assert row2 is not None and row2.status == "published"
    assert await _outbox_count(uow_factory, "content.published.v1") == 1


# --- pin pagination ------------------------------------------------------


async def test_scheduled_publish_then_archive_works(
    publish_ctx: tuple[WorkflowRunner, ContentPublishScanner, CommandContext],
    uow_factory: UoWFactory,
    clock: Any,
    queries: ContentQueries,
) -> None:
    runner, scanner, cmd_ctx = publish_ctx
    created = await create_post(cmd_ctx)
    content_id = uuid.UUID(created.id)
    await ScheduleContent(cmd_ctx)(content_id, clock.utc_now() + timedelta(minutes=5))
    clock.advance(timedelta(minutes=6))
    await scanner.scan_once()
    await runner.run_due(workflow_key=PUBLISH_WORKFLOW_KEY)
    published = await queries.get(content_id)
    assert published is not None and published.status == "published"
    archived = await ArchiveContent(cmd_ctx)(content_id)
    assert archived.status == "archived"
    assert archived.publish_at is None


async def test_pin_pagination_total_and_stable_order(
    ctx: CommandContext, queries: ContentQueries, clock: Any
) -> None:
    ids = []
    for i in range(6):
        created = await create_post(ctx, title=f"post-{i}")
        ids.append(uuid.UUID(created.id))
        if i % 2 == 0:
            await PublishContent(ctx)(ids[-1])
        clock.advance(timedelta(minutes=1))
    pinned = [ids[0], ids[2]]
    await SetContentPin(ctx)(pinned[0], SetContentPinInput(is_pinned=True, pin_rank=1))
    await SetContentPin(ctx)(pinned[1], SetContentPinInput(is_pinned=True, pin_rank=5))

    page1 = await queries.list_contents(page=1, size=4, public_only=True)
    assert page1.total == 3
    assert page1.items[0].id == str(pinned[1])
    assert page1.items[1].id == str(pinned[0])
    assert page1.items[2].id == str(ids[4])
    assert all(item.is_pinned for item in page1.items[:2])
    assert not any(item.is_pinned for item in page1.items[2:])

    page2 = await queries.list_contents(page=2, size=4, public_only=True)
    assert page2.total == 3
    assert len(page2.items) == 0

    full = await queries.list_contents(page=1, size=10, public_only=True)
    assert [item.id for item in full.items[:2]] == [str(pinned[1]), str(pinned[0])]
    assert full.total == 3


async def test_public_list_excludes_drafts(ctx: CommandContext, queries: ContentQueries) -> None:
    created = await create_post(ctx)
    await PublishContent(ctx)(uuid.UUID(created.id))
    await create_post(ctx, title="draft-only")
    page = await queries.list_contents(page=1, size=10, public_only=True)
    assert page.total == 1


# --- references & purge --------------------------------------------------


async def test_replace_references_validates_targets_and_kind(
    ctx: CommandContext, queries: ContentQueries
) -> None:
    source = await create_post(ctx)
    target = await create_post(ctx)
    ghost = uuid.uuid4()
    with pytest.raises(KernelError) as excinfo:
        await ReplaceContentReferences(ctx)(
            uuid.UUID(source.id),
            ReplaceReferencesInput(kind="related", targets=[uuid.UUID(target.id), ghost]),
        )
    assert excinfo.value.code == "content.reference_target_missing"

    page = await CreateContent(ctx)(
        CreateContentInput(type_name="page", title="Page", slug=f"page-{uuid.uuid4().hex[:8]}")
    )
    page_row = await queries.get(uuid.UUID(page.id))
    assert page_row is not None
    with pytest.raises(KernelError) as excinfo:
        await ReplaceContentReferences(ctx)(
            uuid.UUID(source.id),
            ReplaceReferencesInput(kind="related", targets=[uuid.UUID(page.id)]),
        )
    assert excinfo.value.code == "content.reference_target_not_allowed"

    await ReplaceContentReferences(ctx)(
        uuid.UUID(source.id),
        ReplaceReferencesInput(kind="related", targets=[uuid.UUID(target.id)]),
    )
    outgoing = await queries.list_outgoing(uuid.UUID(source.id))
    assert [r.target_content_id for r in outgoing] == [target.id]
    incoming = await queries.list_incoming(uuid.UUID(target.id))
    assert [r.id for r in incoming] == [outgoing[0].id]


async def test_incoming_reference_blocks_purge_but_not_archive(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    source = await create_post(ctx)
    target = await create_post(ctx)
    await PublishContent(ctx)(uuid.UUID(source.id))
    await PublishContent(ctx)(uuid.UUID(target.id))
    await ReplaceContentReferences(ctx)(
        uuid.UUID(source.id), ReplaceReferencesInput(kind="related", targets=[uuid.UUID(target.id)])
    )
    archived = await ArchiveContent(ctx)(uuid.UUID(target.id))
    assert archived.status == "archived"
    with pytest.raises(KernelError) as excinfo:
        await PurgeArchivedContent(ctx)(uuid.UUID(target.id))
    assert excinfo.value.code == "content.incoming_references"


async def test_purge_dry_run_then_real_with_outgoing(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    source = await create_post(ctx)
    target = await create_post(ctx)
    await PublishContent(ctx)(uuid.UUID(source.id))
    await PublishContent(ctx)(uuid.UUID(target.id))
    await ReplaceContentReferences(ctx)(
        uuid.UUID(source.id), ReplaceReferencesInput(kind="related", targets=[uuid.UUID(target.id)])
    )
    await ArchiveContent(ctx)(uuid.UUID(source.id))
    await ArchiveContent(ctx)(uuid.UUID(target.id))

    report = await PurgeArchivedContent(ctx)(uuid.UUID(source.id), dry_run=True)
    assert report["dry_run"] is True and report["outgoing_references"] == 1
    async with uow_factory() as uow:
        assert await uow.session.get(Content, uuid.UUID(source.id)) is not None

    report = await PurgeArchivedContent(ctx)(uuid.UUID(source.id))
    assert report["outgoing_references"] == 1
    async with uow_factory() as uow:
        assert await uow.session.get(Content, uuid.UUID(source.id)) is None
        assert await uow.session.get(Content, uuid.UUID(target.id)) is not None


async def test_purge_requires_archived(ctx: CommandContext) -> None:
    created = await create_post(ctx)
    with pytest.raises(KernelError) as excinfo:
        await PurgeArchivedContent(ctx)(uuid.UUID(created.id))
    assert excinfo.value.code == "content.purge_requires_archived"


# --- owner ---------------------------------------------------------------


async def test_owner_restriction(
    uow_factory: UoWFactory,
    clock: Any,
    types: ContentTypeRegistry,
    schema_registry: EventSchemaRegistry,
) -> None:
    owner_id = uuid.uuid4()
    owner_ctx = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        types=types,
        permissions=ALL_PERMISSIONS,
        actor_id=str(owner_id),
    )
    created = await create_post(owner_ctx, owner_id=owner_id)
    stranger = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        types=types,
        permissions=ALL_PERMISSIONS - {PERMISSION_MANAGE},
        actor_id="stranger",
    )
    with pytest.raises(KernelError) as excinfo:
        await UpdateContent(stranger)(
            uuid.UUID(created.id), UpdateContentInput(expected_version=1, title="hijack")
        )
    assert excinfo.value.code == "content.forbidden"


# --- diagnostics ---------------------------------------------------------


async def test_diagnostics_report_only(
    ctx: CommandContext, queries: ContentQueries, clock: Any, uow_factory: UoWFactory
) -> None:
    diagnostics = ContentDiagnostics(uow_factory=uow_factory, types=ctx.types, clock=clock)
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["content.unknown_type_or_schema"] == "ok"
    assert codes["content.published_missing_time"] == "ok"
    assert codes["content.scheduled_overdue_backlog"] == "ok"
    assert codes["content.orphan_references"] == "ok"

    created = await create_post(ctx)
    await PublishContent(ctx)(uuid.UUID(created.id))
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["content.published_missing_time"] == "ok"

    async with uow_factory() as uow:
        row = (
            (await uow.session.execute(select(Content).where(Content.id == uuid.UUID(created.id))))
            .scalars()
            .first()
        )
        assert row is not None
        row.status = "scheduled"
        row.publish_at = clock.utc_now() - timedelta(days=1)
        await uow.commit()
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["content.scheduled_overdue_backlog"] == "degraded"
