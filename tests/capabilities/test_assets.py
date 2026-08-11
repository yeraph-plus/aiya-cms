"""Assets capability tests.

Contract source: context/spec/capabilities/assets.md §8.

Covers unpredictable object keys, restricted intents, provider-verified
finalize, idempotent finalize/delete through workflows, short-lived URL
resolution without persistence, and recoverable provider failures that
never produce a false ready state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.assets.commands import (
    CommandContext,
    CreateUploadIntent,
    DeleteAsset,
    FinalizeAsset,
    RegisterExternalAsset,
    UpdateAssetMetadata,
    register_asset_workflows,
)
from inc.capabilities.assets.diagnostics import AssetDiagnostics
from inc.capabilities.assets.models import AssetObject, AssetUploadIntent
from inc.capabilities.assets.ports import ObjectStat, StorageError, UploadIntentCredentials
from inc.capabilities.assets.queries import AssetQueries
from inc.capabilities.assets.schemas import (
    CreateUploadIntentInput,
    RegisterExternalAssetInput,
    UpdateAssetMetadataInput,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxWriter
from inc.kernel.workflow import WorkflowRegistry, WorkflowRunner


def _storage_error(message: str) -> StorageError:
    return StorageError(
        code="assets.provider_error",
        category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        message=message,
    )


@dataclass
class FakeObjectStore:
    """In-memory provider; failures can be injected."""

    objects: dict[str, ObjectStat] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    fail_stat: bool = False
    fail_delete: bool = False
    key: str = "fake"

    async def create_upload_intent(self, **_: Any) -> UploadIntentCredentials:
        return UploadIntentCredentials(upload_url="https://storage.example/upload")

    async def stat(self, *, bucket: str | None = None, object_key: str) -> ObjectStat:
        if self.fail_stat:
            raise _storage_error("provider down")
        stat = self.objects.get(object_key)
        if stat is None:
            raise StorageError(
                code="assets.object_missing",
                category=ErrorCategory.NOT_FOUND,
                message="object missing",
            )
        return stat

    async def read_url(
        self, *, bucket: str | None = None, object_key: str, expires_in_seconds: int
    ) -> str:
        return f"https://storage.example/{object_key}?x-expires={expires_in_seconds}"

    async def delete(self, *, bucket: str | None = None, object_key: str) -> None:
        if self.fail_delete:
            raise _storage_error("delete failed")
        self.deleted.append(object_key)
        self.objects.pop(object_key, None)


ALL_PERMISSIONS = frozenset({"assets.read", "assets.upload", "assets.manage", "assets.delete"})


@pytest.fixture
def provider() -> FakeObjectStore:
    return FakeObjectStore()


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded

    registry = EventSchemaRegistry()
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    provider: FakeObjectStore,
    schema_registry: EventSchemaRegistry,
) -> CommandContext:
    workflow_registry = WorkflowRegistry()
    runner = WorkflowRunner(uow_factory=uow_factory, registry=workflow_registry, clock=clock)
    context = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        providers={"fake": provider},
        runner=runner,
        permissions=ALL_PERMISSIONS,
        actor_id="asset-admin",
        trace_id="trace-1",
    )
    register_asset_workflows(workflow_registry, ctx=context)
    return context


async def _run_due(ctx: CommandContext) -> None:
    await ctx.runner.run_due()
    await ctx.runner.run_due()


async def test_create_upload_intent_is_unpredictable_and_restricted(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    a = await CreateUploadIntent(ctx)(
        CreateUploadIntentInput(
            provider_key="fake",
            mime_types=("image/png", "image/jpeg"),
            content_length_max=10_000_000,
        )
    )
    b = await CreateUploadIntent(ctx)(
        CreateUploadIntentInput(
            provider_key="fake",
            mime_types=("image/png",),
            content_length_max=10_000_000,
        )
    )
    assert a.object_key != b.object_key
    assert a.object_key.startswith("uploads/") and len(a.object_key) > len("uploads/")
    assert a.expires_at is not None
    async with uow_factory() as uow:
        intents = (await uow.session.execute(select(AssetUploadIntent))).scalars().all()
    assert len(intents) == 2
    assert all(intent.mime_types for intent in intents)


async def test_finalize_requires_upload_permission(
    uow_factory: UoWFactory,
    clock: Any,
    provider: FakeObjectStore,
    schema_registry: EventSchemaRegistry,
) -> None:
    restricted = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        providers={"fake": provider},
        runner=None,  # type: ignore[arg-type]
        permissions=frozenset({"assets.read"}),
    )
    with pytest.raises(KernelError) as excinfo:
        await FinalizeAsset(restricted)(uuid.uuid4())
    assert excinfo.value.code == "assets.forbidden"


async def test_finalize_verifies_stat_and_marks_ready(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    intent = await CreateUploadIntent(ctx)(
        CreateUploadIntentInput(
            provider_key="fake",
            mime_types=("image/png",),
            content_length_max=10_000_000,
            checksum_sha256="a" * 64,
        )
    )
    provider = ctx.providers["fake"]
    provider.objects[intent.object_key] = ObjectStat(
        byte_size=1024, mime_type="image/png", checksum_sha256="a" * 64
    )
    result = await FinalizeAsset(ctx)(uuid.UUID(intent.intent_id))
    assert result.state == "pending"
    await _run_due(ctx)
    queries = AssetQueries(ctx=ctx, clock=clock)
    ALL = frozenset({"assets.read"})
    from sqlalchemy import select as sa_select

    async with uow_factory() as uow:
        asset_row = (
            (
                await uow.session.execute(
                    sa_select(AssetObject).where(AssetObject.object_key == result.object_key)
                )
            )
            .scalars()
            .first()
        )
    assert asset_row is not None
    ref = await queries.get(asset_row.id, permissions=ALL)
    assert ref is not None and ref.state == "ready"
    assert ref.mime_type == "image/png" and ref.byte_size == 1024
    async with uow_factory() as uow:
        stored = (await uow.session.execute(sa_select(AssetObject))).scalars().all()
        intent_row = await uow.session.get(AssetUploadIntent, uuid.UUID(intent.intent_id))
    assert len(stored) == 1
    assert intent_row is not None and intent_row.consumed_at is not None


async def test_finalize_rejects_size_mime_checksum_mismatch(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    intent = await CreateUploadIntent(ctx)(
        CreateUploadIntentInput(
            provider_key="fake",
            mime_types=("image/png",),
            content_length_max=1_000,
            checksum_sha256="c" * 64,
        )
    )
    provider = ctx.providers["fake"]
    provider.objects[intent.object_key] = ObjectStat(
        byte_size=5000, mime_type="application/pdf", checksum_sha256="d" * 64
    )
    await FinalizeAsset(ctx)(uuid.UUID(intent.intent_id))
    await _run_due(ctx)
    async with uow_factory() as uow:
        assets = (await uow.session.execute(select(AssetObject))).scalars().all()
        intent_row = await uow.session.get(AssetUploadIntent, uuid.UUID(intent.intent_id))
    assert assets == []
    assert intent_row is not None and intent_row.consumed_at is None
    workflow = await _due_workflow_state(ctx)
    assert workflow == "failed"


async def _due_workflow_state(ctx: CommandContext) -> str:
    from inc.kernel.workflow.models import WorkflowInstance

    async with ctx.uow_factory() as uow:
        rows = (await uow.session.execute(select(WorkflowInstance))).scalars().all()
        return rows[0].status if rows else "none"


async def test_provider_failure_recovers_after_retry(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    intent = await CreateUploadIntent(ctx)(
        CreateUploadIntentInput(
            provider_key="fake",
            mime_types=("image/png",),
            content_length_max=1_000_000,
        )
    )
    provider = ctx.providers["fake"]
    provider.objects[intent.object_key] = ObjectStat(byte_size=100, mime_type="image/png")
    provider.fail_stat = True
    await FinalizeAsset(ctx)(uuid.UUID(intent.intent_id))
    await ctx.runner.run_due()
    async with uow_factory() as uow:
        assets = (await uow.session.execute(select(AssetObject))).scalars().all()
    assert assets == []  # no false ready on failure

    provider.fail_stat = False
    clock.advance(timedelta(seconds=30))  # past the retry backoff
    await ctx.runner.run_due()  # retry path re-runs the failed step
    async with uow_factory() as uow:
        assets = (await uow.session.execute(select(AssetObject))).scalars().all()
    assert len(assets) == 1 and assets[0].state == "ready"


async def test_register_external_asset(ctx: CommandContext, uow_factory: UoWFactory) -> None:
    provider = ctx.providers["fake"]
    provider.objects["existing/logo.png"] = ObjectStat(
        byte_size=2048, mime_type="image/png", checksum_sha256="b" * 64
    )
    ref = await RegisterExternalAsset(ctx)(
        RegisterExternalAssetInput(
            provider_key="fake",
            bucket="media",
            object_key="existing/logo.png",
            mime_type="image/png",
            byte_size=2048,
            checksum_sha256="b" * 64,
            alt_text="Logo",
        )
    )
    assert ref.state == "ready" and ref.bucket == "media"
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(AssetObject))).scalars().all()
    assert len(rows) == 1


async def test_update_metadata_and_delete_via_workflow(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    provider = ctx.providers["fake"]
    provider.objects["to/delete.png"] = ObjectStat(byte_size=10, mime_type="image/png")
    ref = await RegisterExternalAsset(ctx)(
        RegisterExternalAssetInput(
            provider_key="fake", object_key="to/delete.png", mime_type="image/png", byte_size=10
        )
    )
    updated = await UpdateAssetMetadata(ctx)(
        uuid.UUID(ref.id), UpdateAssetMetadataInput(alt_text="New alt", metadata={"by": "t"})
    )
    assert updated.alt_text == "New alt"
    await DeleteAsset(ctx)(uuid.UUID(ref.id))
    await _run_due(ctx)
    async with uow_factory() as uow:
        row = await uow.session.get(AssetObject, uuid.UUID(ref.id))
    assert row is not None
    assert row.state == "deleted" and row.external_deleted_at is not None
    assert provider.deleted == ["to/delete.png"]


async def test_delete_is_idempotent_under_retry(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    provider = ctx.providers["fake"]
    provider.objects["to/delete2.png"] = ObjectStat(byte_size=10, mime_type="image/png")
    ref = await RegisterExternalAsset(ctx)(
        RegisterExternalAssetInput(
            provider_key="fake", object_key="to/delete2.png", mime_type="image/png", byte_size=10
        )
    )
    provider.fail_delete = True
    await DeleteAsset(ctx)(uuid.UUID(ref.id))
    await ctx.runner.run_due()
    provider.fail_delete = False
    clock.advance(timedelta(seconds=30))  # past the retry backoff
    await ctx.runner.run_due()
    async with uow_factory() as uow:
        row = await uow.session.get(AssetObject, uuid.UUID(ref.id))
    assert row is not None and row.external_deleted_at is not None
    assert provider.deleted == ["to/delete2.png"]


async def test_resolve_url_not_persisted_and_has_expiry(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    provider = ctx.providers["fake"]
    provider.objects["pub/1.png"] = ObjectStat(byte_size=5, mime_type="image/png")
    ref = await RegisterExternalAsset(ctx)(
        RegisterExternalAssetInput(
            provider_key="fake", object_key="pub/1.png", mime_type="image/png", byte_size=5
        )
    )
    resolved = await AssetQueries(ctx=ctx, clock=clock).resolve_url(
        uuid.UUID(ref.id), expires_in_seconds=120, permissions=frozenset({"assets.read"})
    )
    assert "x-expires=120" in resolved.url
    async with uow_factory() as uow:
        raw = await uow.session.execute(select(AssetObject.object_key, AssetObject.asset_metadata))
        rows = raw.all()
    assert not any("x-expires" in str(row) for row in rows)


async def test_diagnostics_report_only(
    ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    diagnostics = AssetDiagnostics(
        uow_factory=uow_factory,
        clock=clock,
        providers=ctx.providers,
        probe_remote=True,
    )
    results = await diagnostics.run()
    codes = {r.code: r.status.value for r in results}
    assert codes["assets.expired_pending_intents"] == "ok"
    assert codes["assets.unresolved_objects"] == "ok"
    assert codes["assets.ready_but_remote_missing"] == "ok"


async def test_duplicate_register_external_conflicts(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    provider = ctx.providers["fake"]
    provider.objects["dup.png"] = ObjectStat(byte_size=10, mime_type="image/png")
    payload = RegisterExternalAssetInput(
        provider_key="fake", object_key="dup.png", mime_type="image/png", byte_size=10
    )
    await RegisterExternalAsset(ctx)(payload)
    with pytest.raises(KernelError) as excinfo:
        await RegisterExternalAsset(ctx)(payload)
    assert excinfo.value.code == "assets.already_registered"


async def test_failed_finalize_reports_explicitly_and_blocks_retry(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    intent = await CreateUploadIntent(ctx)(
        CreateUploadIntentInput(
            provider_key="fake",
            mime_types=("image/png",),
            content_length_max=100,
        )
    )
    provider = ctx.providers["fake"]
    provider.objects[intent.object_key] = ObjectStat(
        byte_size=9999,
        mime_type="image/png",  # exceeds content_length_max
    )
    await FinalizeAsset(ctx)(uuid.UUID(intent.intent_id))
    await _run_due(ctx)
    async with uow_factory() as uow:
        assets = (await uow.session.execute(select(AssetObject))).scalars().all()
    assert assets == []
    with pytest.raises(KernelError) as excinfo:
        await FinalizeAsset(ctx)(uuid.UUID(intent.intent_id))
    assert excinfo.value.code == "assets.finalize_failed"


async def test_permanent_provider_error_fails_fast_without_retries(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    intent = await CreateUploadIntent(ctx)(
        CreateUploadIntentInput(
            provider_key="fake",
            mime_types=("image/png",),
            content_length_max=1_000_000,
        )
    )
    # object never uploaded: provider stat reports NOT_FOUND (permanent)
    await FinalizeAsset(ctx)(uuid.UUID(intent.intent_id))
    await _run_due(ctx)
    workflow_state = await _due_workflow_state(ctx)
    assert workflow_state == "failed"
    with pytest.raises(KernelError) as excinfo:
        await FinalizeAsset(ctx)(uuid.UUID(intent.intent_id))
    assert excinfo.value.code == "assets.finalize_failed"


async def test_reconciler_restarts_orphaned_delete(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    from inc.capabilities.assets.commands import AssetDeleteReconciler

    provider = ctx.providers["fake"]
    provider.objects["reconcile.png"] = ObjectStat(byte_size=10, mime_type="image/png")
    ref = await RegisterExternalAsset(ctx)(
        RegisterExternalAssetInput(
            provider_key="fake", object_key="reconcile.png", mime_type="image/png", byte_size=10
        )
    )
    # simulate the crash window: mark deleted locally without starting workflow
    async with uow_factory() as uow:
        row = await uow.session.get(AssetObject, uuid.UUID(ref.id))
        assert row is not None
        row.state = "deleted"
        await uow.commit()
    reconciler = AssetDeleteReconciler(ctx=ctx)
    assert await reconciler.scan() == 1
    assert await reconciler.scan() == 0  # already started; idempotent
    await _run_due(ctx)
    async with uow_factory() as uow:
        row = await uow.session.get(AssetObject, uuid.UUID(ref.id))
    assert row is not None and row.external_deleted_at is not None
    assert provider.deleted == ["reconcile.png"]


async def test_delete_audits_requested_then_external(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    from sqlalchemy import select as sa_select

    from inc.kernel.events import OutboxMessage

    provider = ctx.providers["fake"]
    provider.objects["audit.png"] = ObjectStat(byte_size=10, mime_type="image/png")
    ref = await RegisterExternalAsset(ctx)(
        RegisterExternalAssetInput(
            provider_key="fake", object_key="audit.png", mime_type="image/png", byte_size=10
        )
    )
    await DeleteAsset(ctx)(uuid.UUID(ref.id))
    async with uow_factory() as uow:
        actions = (await uow.session.execute(sa_select(OutboxMessage))).scalars().all()
    actions_before = [row.envelope.payload["action"] for row in actions]
    assert "assets.delete.requested" in actions_before
    assert "assets.delete.external" not in actions_before
    await _run_due(ctx)
    async with uow_factory() as uow:
        actions = (await uow.session.execute(sa_select(OutboxMessage))).scalars().all()
    actions_after = [row.envelope.payload["action"] for row in actions]
    assert "assets.delete.external" in actions_after
    assert "assets.register_external" in actions_after
