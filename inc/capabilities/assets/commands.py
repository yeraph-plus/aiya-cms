"""Assets commands and workflows.

Contract source: context/spec/capabilities/assets.md §5/§6.

Provider calls never bind to long database transactions: FinalizeAsset and
DeleteAsset mark local state and start idempotent workflows whose single
activity performs the provider call and persists the outcome in its own
commit. Provider credentials and signed URLs never enter the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from inc.capabilities.assets.models import (
    AssetMetadata,
    AssetObject,
    AssetUploadIntent,
)
from inc.capabilities.assets.ports import (
    ObjectStorageProvider,
    StorageError,
    permanent_storage_error,
    storage_error,
)
from inc.capabilities.assets.schemas import (
    AssetRefDTO,
    CreateUploadIntentInput,
    CreateUploadIntentResult,
    FinalizeResultDTO,
    RegisterExternalAssetInput,
    UpdateAssetMetadataInput,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock
from inc.kernel.workflow import (
    ActivityContext,
    ActivitySpec,
    RetryPolicy,
    WorkflowRegistry,
    WorkflowRunner,
    WorkflowSpec,
)

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"

PERMISSION_READ = "assets.read"
PERMISSION_UPLOAD = "assets.upload"
PERMISSION_MANAGE = "assets.manage"
PERMISSION_DELETE = "assets.delete"

FINALIZE_WORKFLOW_KEY = "assets.finalize.v1"
DELETE_WORKFLOW_KEY = "assets.delete.v1"
FINALIZE_ACTIVITY_KEY = "assets.finalize.step.v1"
DELETE_ACTIVITY_KEY = "assets.delete.step.v1"

INTENT_TTL_SECONDS = 60 * 60


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    providers: dict[str, ObjectStorageProvider]
    runner: WorkflowRunner
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None


def _forbidden(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.FORBIDDEN, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


def _validation(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


def _require_permission(ctx: CommandContext, key: str) -> None:
    if key not in ctx.permissions:
        raise _forbidden("assets.forbidden", f"requires permission {key}")


def _provider(ctx: CommandContext, provider_key: str) -> ObjectStorageProvider:
    provider = ctx.providers.get(provider_key)
    if provider is None:
        raise _validation("assets.unknown_provider", f"provider {provider_key!r} is not configured")
    return provider


def _ensure_utc(value: Any) -> Any:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _new_object_key() -> str:
    raw = uuid.uuid4().hex
    return f"uploads/{raw[:8]}/{raw[8:16]}/{raw[16:]}"


async def _append_audit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    action: str,
    target_type: str,
    target_id: str,
    occurred_at: Any | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    now = occurred_at if occurred_at is not None else ctx.clock.utc_now()
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=now,
            producer="assets",
            aggregate_type="assets",
            aggregate_id=target_id,
            trace_id=ctx.trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": now.isoformat(),
                "actor_type": "user" if ctx.actor_id else None,
                "actor_id": ctx.actor_id,
                "target_type": target_type,
                "target_id": target_id,
                "trace_id": ctx.trace_id,
                "details": details or {},
            },
        ),
    )


def _to_ref(row: AssetObject) -> AssetRefDTO:
    return AssetRefDTO(
        id=str(row.id),
        provider_key=row.provider_key,
        bucket=row.bucket,
        object_key=row.object_key,
        mime_type=row.mime_type,
        byte_size=row.byte_size,
        checksum_sha256=row.checksum_sha256,
        alt_text=row.alt_text,
        metadata=dict(row.asset_metadata.values),
        state=row.state,
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


class CreateUploadIntent:
    """Allocate an unpredictable object key with restricted upload terms."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, input_: CreateUploadIntentInput
    ) -> CreateUploadIntentResult:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_UPLOAD)
        provider = _provider(ctx, input_.provider_key)
        object_key = _new_object_key()
        expires_at = ctx.clock.utc_now() + timedelta(seconds=INTENT_TTL_SECONDS)
        try:
            credentials = await provider.create_upload_intent(
                object_key=object_key,
                content_length_max=input_.content_length_max,
                mime_types=input_.mime_types,
                checksum_sha256=input_.checksum_sha256,
                expires_at=expires_at,
            )
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - adapter errors map to storage errors
            raise storage_error(str(exc)) from exc
        async with ctx.uow_factory() as uow:
            intent = AssetUploadIntent(
                provider_key=input_.provider_key,
                object_key=object_key,
                content_length_max=input_.content_length_max,
                mime_types=",".join(input_.mime_types),
                checksum_sha256=input_.checksum_sha256,
                expires_at=expires_at,
            )
            uow.session.add(intent)
            await uow.session.flush()  # assign id before audit references it
            await _append_audit(
                ctx,
                uow,
                action="assets.create_upload_intent",
                target_type="upload_intent",
                target_id=str(intent.id),
            )
            await uow.commit()
            return CreateUploadIntentResult(
                intent_id=str(intent.id),
                object_key=object_key,
                upload_url=credentials.upload_url,
                headers=credentials.headers,
                expires_at=expires_at,
            )


class FinalizeAsset:
    """Verify the uploaded object through the provider, then start the
    finalize workflow (idempotent by intent id)."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, intent_id: Any) -> FinalizeResultDTO:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_UPLOAD)
        async with ctx.uow_factory() as read_uow:
            intent: AssetUploadIntent | None = await read_uow.session.get(
                AssetUploadIntent, intent_id
            )
        if intent is None:
            raise KernelError(
                code="assets.intent_not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"upload intent {intent_id}",
            )
        if intent.consumed_at is not None:
            raise _conflict("assets.intent_consumed", "upload intent already consumed")
        if _ensure_utc(intent.expires_at) < ctx.clock.utc_now():
            raise _conflict("assets.intent_expired", "upload intent expired")
        previous = await _workflow_status(ctx, FINALIZE_WORKFLOW_KEY, f"intent:{intent_id}")
        if previous == "failed":
            raise _conflict(
                "assets.finalize_failed",
                "finalize previously failed with a permanent error; create a new upload intent",
            )
        try:
            await ctx.runner.start(
                workflow_key=FINALIZE_WORKFLOW_KEY,
                idempotency_key=f"intent:{intent_id}",
                input_data={"intent_id": str(intent_id)},
                trace_id=ctx.trace_id,
            )
        except IntegrityError:
            # concurrent start: the workflow already exists, treat as started
            pass
        return FinalizeResultDTO(intent_id=str(intent_id), object_key=intent.object_key)


class RegisterExternalAsset:
    """Trusted server-side registration of an already existing object."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: RegisterExternalAssetInput) -> AssetRefDTO:  # type: ignore[return]
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_MANAGE)
        provider = _provider(ctx, input_.provider_key)
        try:
            stat = await provider.stat(object_key=input_.object_key)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors map to storage errors
            raise storage_error(str(exc)) from exc
        if input_.checksum_sha256 is not None and stat.checksum_sha256 is not None:
            if stat.checksum_sha256 != input_.checksum_sha256:
                raise permanent_storage_error(
                    "assets.checksum_mismatch", "checksum does not match remote object"
                )
        async with ctx.uow_factory() as uow:
            duplicate = (
                (
                    await uow.session.execute(
                        select(AssetObject.id).where(
                            AssetObject.provider_key == input_.provider_key,
                            AssetObject.object_key == input_.object_key,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if duplicate is not None:
                raise _conflict(
                    "assets.already_registered",
                    f"object {input_.object_key!r} is already registered on {input_.provider_key}",
                )
            row = AssetObject(
                provider_key=input_.provider_key,
                bucket=input_.bucket,
                object_key=input_.object_key,
                mime_type=stat.mime_type,
                byte_size=stat.byte_size,
                checksum_sha256=stat.checksum_sha256,
                alt_text=input_.alt_text,
                asset_metadata=AssetMetadata(values=input_.metadata),
                state="ready",
            )
            uow.session.add(row)
            await uow.session.flush()  # assign id before audit references it
            await _append_audit(
                ctx,
                uow,
                action="assets.register_external",
                target_type="asset",
                target_id=str(row.id),
                details={"object_key": row.object_key},
            )
            try:
                await uow.commit()
            except IntegrityError as exc:
                raise _conflict(
                    "assets.already_registered",
                    f"object {input_.object_key!r} is already registered",
                ) from exc
            return _to_ref(row)


class UpdateAssetMetadata:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, asset_id: Any, input_: UpdateAssetMetadataInput
    ) -> AssetRefDTO:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_MANAGE)
        async with ctx.uow_factory() as uow:
            row: AssetObject | None = await uow.session.get(AssetObject, asset_id)
            if row is None:
                raise KernelError(
                    code="assets.not_found",
                    category=ErrorCategory.NOT_FOUND,
                    message=f"asset {asset_id}",
                )
            if row.state not in ("ready", "pending"):
                raise _conflict(
                    "assets.state_immutable", "metadata only editable while ready/pending"
                )
            if input_.alt_text is not None:
                row.alt_text = input_.alt_text
            if input_.metadata is not None:
                row.asset_metadata = AssetMetadata(values=input_.metadata)
            await _append_audit(
                ctx,
                uow,
                action="assets.update_metadata",
                target_type="asset",
                target_id=str(row.id),
            )
            await uow.commit()
            return _to_ref(row)


class DeleteAsset:
    """Mark deleted locally, then start the delete workflow."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, asset_id: Any) -> None:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_DELETE)
        async with ctx.uow_factory() as uow:
            row: AssetObject | None = await uow.session.get(AssetObject, asset_id)
            if row is None:
                raise KernelError(
                    code="assets.not_found",
                    category=ErrorCategory.NOT_FOUND,
                    message=f"asset {asset_id}",
                )
            if row.state in ("deleted", "pending"):
                raise _conflict("assets.not_deletable", f"asset is {row.state}")
            row.state = "deleted"
            row.deleted_at = ctx.clock.utc_now()
            await _append_audit(
                ctx,
                uow,
                action="assets.delete.requested",
                target_type="asset",
                target_id=str(row.id),
                details={"object_key": row.object_key},
            )
            await uow.commit()
        await ctx.runner.start(
            workflow_key=DELETE_WORKFLOW_KEY,
            idempotency_key=f"asset:{asset_id}",
            input_data={"asset_id": str(asset_id)},
            trace_id=ctx.trace_id,
        )


async def _workflow_status(ctx: CommandContext, workflow_key: str, idempotency_key: str) -> str:  # type: ignore[return]
    from inc.kernel.workflow.models import WorkflowInstance

    async with ctx.uow_factory() as uow:
        row = (
            (
                await uow.session.execute(
                    select(WorkflowInstance).where(
                        WorkflowInstance.workflow_key == workflow_key,
                        WorkflowInstance.business_idempotency_key == idempotency_key,
                    )
                )
            )
            .scalars()
            .first()
        )
        return row.status if row is not None else "none"


class FinalizeActivity:
    """Provider stat + verification + ready transition in one step commit."""

    def __init__(self, *, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self, uow: UnitOfWork, data: dict[str, Any], activity_ctx: ActivityContext
    ) -> dict[str, Any]:
        ctx = self._ctx
        intent_id = data.get("workflow", {}).get("intent_id")
        if intent_id is None:
            raise KernelError(
                code="assets.finalize_invalid_input",
                category=ErrorCategory.INTERNAL,
                message="finalize workflow input is missing intent_id",
            )
        try:
            parsed_id = uuid.UUID(intent_id)
        except ValueError as exc:
            raise KernelError(
                code="assets.finalize_invalid_input",
                category=ErrorCategory.INTERNAL,
                message="finalize workflow input carries an invalid intent_id",
            ) from exc
        intent: AssetUploadIntent | None = await uow.session.get(AssetUploadIntent, parsed_id)
        if intent is None or intent.consumed_at is not None:
            return {"skipped": True}
        provider = _provider(ctx, intent.provider_key)
        try:
            stat = await provider.stat(object_key=intent.object_key)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors map to storage errors
            raise storage_error(str(exc)) from exc
        if stat.byte_size > intent.content_length_max:
            raise permanent_storage_error("assets.size_exceeded", "object larger than allowed")
        if stat.mime_type not in intent.mime_types.split(","):
            raise permanent_storage_error(
                "assets.mime_not_allowed", f"mime {stat.mime_type!r} not allowed"
            )
        if intent.checksum_sha256 is not None:
            if stat.checksum_sha256 is None:
                raise permanent_storage_error(
                    "assets.checksum_unverifiable",
                    "provider cannot verify the required checksum",
                )
            if stat.checksum_sha256 != intent.checksum_sha256:
                raise permanent_storage_error(
                    "assets.checksum_mismatch", "checksum does not match intent"
                )
        now = ctx.clock.utc_now()
        row = AssetObject(
            provider_key=intent.provider_key,
            object_key=intent.object_key,
            mime_type=stat.mime_type,
            byte_size=stat.byte_size,
            checksum_sha256=stat.checksum_sha256 or intent.checksum_sha256,
            asset_metadata=AssetMetadata(values={}),
            state="ready",
        )
        uow.session.add(row)
        await uow.session.flush()  # assign id before audit references it
        intent.consumed_at = now
        await _append_audit(
            ctx,
            uow,
            action="assets.finalize",
            target_type="asset",
            target_id=str(row.id),
            occurred_at=now,
            details={"object_key": row.object_key},
        )
        return {"skipped": False, "asset_state": "ready", "asset_id": str(row.id)}


class DeleteActivity:
    """Provider delete + external_deleted_at in one step commit; idempotent.

    The provider Port contract requires delete to be idempotent (deleting
    a missing object is success), so a retried step never double-executes
    a side effect.
    """

    def __init__(self, *, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self, uow: UnitOfWork, data: dict[str, Any], activity_ctx: ActivityContext
    ) -> dict[str, Any]:
        ctx = self._ctx
        asset_id = data.get("workflow", {}).get("asset_id")
        if asset_id is None:
            raise KernelError(
                code="assets.delete_invalid_input",
                category=ErrorCategory.INTERNAL,
                message="delete workflow input is missing asset_id",
            )
        try:
            parsed_id = uuid.UUID(asset_id)
        except ValueError as exc:
            raise KernelError(
                code="assets.delete_invalid_input",
                category=ErrorCategory.INTERNAL,
                message="delete workflow input carries an invalid asset_id",
            ) from exc
        row: AssetObject | None = await uow.session.get(AssetObject, parsed_id)
        if row is None or row.external_deleted_at is not None:
            return {"skipped": True}
        provider = _provider(ctx, row.provider_key)
        try:
            await provider.delete(object_key=row.object_key)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors map to storage errors
            raise storage_error(str(exc)) from exc
        now = ctx.clock.utc_now()
        row.external_deleted_at = now
        await _append_audit(
            ctx,
            uow,
            action="assets.delete.external",
            target_type="asset",
            target_id=str(row.id),
            occurred_at=now,
            details={"object_key": row.object_key},
        )
        return {"skipped": False}


class AssetDeleteReconciler:
    """Re-starts delete workflows for rows left deleted-but-unconfirmed.

    Covers the crash window between DeleteAsset's local commit and the
    workflow start; workflow start is idempotent by asset id.
    """

    def __init__(self, *, ctx: CommandContext, batch: int = 64) -> None:
        self._ctx = ctx
        self._batch = batch

    async def scan(self) -> int:
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(AssetObject)
                        .where(
                            AssetObject.state == "deleted",
                            AssetObject.external_deleted_at.is_(None),
                        )
                        .order_by(AssetObject.updated_at)
                        .limit(self._batch)
                    )
                )
                .scalars()
                .all()
            )
        restarted = 0
        for row in rows:
            previous = await _workflow_status(ctx, DELETE_WORKFLOW_KEY, f"asset:{row.id}")
            if previous != "none":
                continue
            await ctx.runner.start(
                workflow_key=DELETE_WORKFLOW_KEY,
                idempotency_key=f"asset:{row.id}",
                input_data={"asset_id": str(row.id)},
                trace_id=f"reconcile:{row.id}",
            )
            restarted += 1
        return restarted


def build_asset_workflow_specs(ctx: CommandContext) -> tuple[WorkflowSpec, ...]:
    finalize = WorkflowSpec(
        key=FINALIZE_WORKFLOW_KEY,
        version="1",
        activities=(
            ActivitySpec(
                key=FINALIZE_ACTIVITY_KEY,
                timeout_seconds=30.0,
                retry=RetryPolicy(max_attempts=5, base_delay_seconds=1.0),
                handler=FinalizeActivity(ctx=ctx),
            ),
        ),
    )
    delete = WorkflowSpec(
        key=DELETE_WORKFLOW_KEY,
        version="1",
        activities=(
            ActivitySpec(
                key=DELETE_ACTIVITY_KEY,
                timeout_seconds=30.0,
                retry=RetryPolicy(max_attempts=5, base_delay_seconds=1.0),
                handler=DeleteActivity(ctx=ctx),
            ),
        ),
    )
    return finalize, delete


def register_asset_workflows(registry: WorkflowRegistry, *, ctx: CommandContext) -> None:
    for spec in build_asset_workflow_specs(ctx):
        registry.register(spec)
