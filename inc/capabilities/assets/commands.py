"""Assets commands and workflows.

Contract source: context/spec/capabilities/assets.md §5/§6.

Provider calls never bind to long database transactions: FinalizeAsset and
DeleteAsset mark local state and start idempotent workflows whose single
activity performs the provider call and persists the outcome in its own
commit. Provider credentials and signed URLs never enter the database.
"""

from __future__ import annotations

import uuid
import warnings
from dataclasses import dataclass, replace
from datetime import UTC, timedelta
from io import BytesIO
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
CONTENT_IMAGE_FINALIZE_WORKFLOW_KEY = "assets.contentimagefinalize.v1"
CONTENT_IMAGE_NORMALIZE_ACTIVITY_KEY = "assets.contentimagenormalize.step.v1"

INTENT_TTL_SECONDS = 60 * 60
CONTENT_IMAGE_MAX_SOURCE_BYTES = 20 * 1024 * 1024


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
                bucket=input_.bucket,
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
                owner_subject_id=ctx.actor_id,
                bucket=input_.bucket,
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
        return await _start_finalize_workflow(
            ctx,
            intent_id,
            workflow_key=FINALIZE_WORKFLOW_KEY,
            idempotency_key=f"intent:{intent_id}",
            input_data={"intent_id": str(intent_id)},
        )


class FinalizeContentImage:
    """Start assets-owned upload verification and image normalization.

    The content-bucket feature calls this public capability command once. A
    two-step assets workflow then verifies the private upload and produces a
    public WebP derivative. Polling its result is read-only and never needs
    to re-run a feature command.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, intent_id: Any, *, max_edge: int, quality: int) -> FinalizeResultDTO:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_UPLOAD)
        _require_permission(ctx, PERMISSION_MANAGE)
        if not 1 <= max_edge <= 8192 or not 40 <= quality <= 100:
            raise _validation("assets.invalid_image_profile", "invalid image normalization profile")
        return await _start_finalize_workflow(
            ctx,
            intent_id,
            workflow_key=CONTENT_IMAGE_FINALIZE_WORKFLOW_KEY,
            idempotency_key=f"content-intent:{intent_id}",
            input_data={
                "intent_id": str(intent_id),
                "max_edge": max_edge,
                "quality": quality,
            },
        )


async def _start_finalize_workflow(
    ctx: CommandContext,
    intent_id: Any,
    *,
    workflow_key: str,
    idempotency_key: str,
    input_data: dict[str, Any],
) -> FinalizeResultDTO:
    async with ctx.uow_factory() as read_uow:
        intent: AssetUploadIntent | None = await read_uow.session.get(AssetUploadIntent, intent_id)
    if intent is None:
        raise KernelError(
            code="assets.intent_not_found",
            category=ErrorCategory.NOT_FOUND,
            message=f"upload intent {intent_id}",
        )
    if (
        intent.owner_subject_id is not None
        and ctx.actor_id is not None
        and intent.owner_subject_id != ctx.actor_id
    ):
        raise _forbidden("assets.forbidden", "upload intent belongs to another subject")
    if intent.consumed_at is not None:
        raise _conflict("assets.intent_consumed", "upload intent already consumed")
    if _ensure_utc(intent.expires_at) < ctx.clock.utc_now():
        raise _conflict("assets.intent_expired", "upload intent expired")
    previous = await _workflow_status(ctx, workflow_key, idempotency_key)
    if previous == "failed":
        raise _conflict(
            "assets.finalize_failed",
            "finalize previously failed with a permanent error; create a new upload intent",
        )
    try:
        await ctx.runner.start(
            workflow_key=workflow_key,
            idempotency_key=idempotency_key,
            input_data=input_data,
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
            stat = await provider.stat(bucket=input_.bucket, object_key=input_.object_key)
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
                bucket=input_.bucket or stat.bucket,
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


@dataclass(frozen=True, slots=True)
class NormalizedImageResult:
    asset: AssetRefDTO
    public_url: str


class NormalizeContentImage:
    """Replace a ready private upload with a normalized public WebP asset.

    The feature chooses the content profile; this capability owns every
    storage read/write/delete and never exposes the S3 client to a feature.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self, source_asset_id: Any, *, max_edge: int, quality: int
    ) -> NormalizedImageResult:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_MANAGE)
        if not 1 <= max_edge <= 8192 or not 40 <= quality <= 100:
            raise _validation("assets.invalid_image_profile", "invalid image normalization profile")
        async with ctx.uow_factory() as uow:
            source: AssetObject | None = await uow.session.get(AssetObject, source_asset_id)
        if source is None:
            raise KernelError(
                code="assets.not_found",
                category=ErrorCategory.NOT_FOUND,
                message=f"asset {source_asset_id}",
            )
        if source.state != "ready" or source.deleted_at is not None or source.bucket == "content":
            raise _conflict("assets.not_normalizable", "asset is not a private ready upload")
        if source.byte_size > CONTENT_IMAGE_MAX_SOURCE_BYTES:
            await self._discard_source(source)
            raise permanent_storage_error("assets.image_too_large", "source image exceeds 20 MiB")
        provider = _provider(ctx, source.provider_key)
        object_key: str | None = None
        try:
            raw = await provider.read_bytes(bucket=source.bucket, object_key=source.object_key)
            if len(raw) > CONTENT_IMAGE_MAX_SOURCE_BYTES:
                raise permanent_storage_error(
                    "assets.image_too_large", "source image exceeds 20 MiB"
                )
            normalized = _normalize_webp(raw, max_edge=max_edge, quality=quality)
            object_key = _new_content_object_key()
            stat = await provider.put_bytes(
                bucket="content", object_key=object_key, body=normalized, mime_type="image/webp"
            )
            public_url = await provider.public_url(bucket="content", object_key=object_key)
        except Exception:
            if object_key is not None:
                try:
                    await provider.delete(bucket="content", object_key=object_key)
                except Exception:  # noqa: BLE001 - preserve the original transform failure
                    pass
            await self._discard_source(source)
            raise
        assert object_key is not None
        final: AssetObject | None = None
        try:
            async with ctx.uow_factory() as uow:
                current: AssetObject | None = await uow.session.get(AssetObject, source.id)
                if current is None or current.state != "ready":
                    raise _conflict(
                        "assets.source_changed", "source asset changed during normalization"
                    )
                final = AssetObject(
                    provider_key=source.provider_key,
                    bucket="content",
                    object_key=object_key,
                    mime_type="image/webp",
                    byte_size=stat.byte_size,
                    checksum_sha256=stat.checksum_sha256,
                    asset_metadata=AssetMetadata(
                        values={
                            "public_url": public_url,
                            "normalized": True,
                            "source_asset_id": str(source.id),
                        }
                    ),
                    state="ready",
                )
                uow.session.add(final)
                current.state = "deleted"
                current.deleted_at = ctx.clock.utc_now()
                current.external_deleted_at = ctx.clock.utc_now()
                await _append_audit(
                    ctx,
                    uow,
                    action="assets.content_image.normalized",
                    target_type="asset",
                    target_id=str(final.id),
                    details={"source_asset_id": str(source.id), "object_key": object_key},
                )
                await uow.session.flush()
                await uow.commit()
        except Exception:
            try:
                await provider.delete(bucket="content", object_key=object_key)
            except Exception:  # noqa: BLE001 - preserve the database failure
                pass
            raise
        try:
            await provider.delete(bucket=source.bucket, object_key=source.object_key)
        except StorageError:
            # The source is already logically deleted and the cleanup worker will reconcile it.
            pass
        assert final is not None
        return NormalizedImageResult(asset=_to_ref(final), public_url=public_url)

    async def _discard_source(self, source: AssetObject) -> None:
        """Best-effort source cleanup on every failed transform; originals never persist."""

        ctx = self._ctx
        provider = _provider(ctx, source.provider_key)
        try:
            await provider.delete(bucket=source.bucket, object_key=source.object_key)
        except Exception:  # noqa: BLE001 - source cleanup cannot mask validation failure
            pass
        async with ctx.uow_factory() as uow:
            row: AssetObject | None = await uow.session.get(AssetObject, source.id)
            if row is not None and row.state == "ready":
                row.state = "deleted"
                row.deleted_at = ctx.clock.utc_now()
                row.external_deleted_at = ctx.clock.utc_now()
                await uow.commit()


def _new_content_object_key() -> str:
    raw = uuid.uuid4().hex
    return f"content/{raw[:2]}/{raw}.webp"


def _normalize_webp(raw: bytes, *, max_edge: int, quality: int) -> bytes:
    """Decode only raster images and write a bounded, single-frame WebP."""

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency is a release requirement
        raise storage_error("image processing dependency is unavailable") from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                source.verify()
            with Image.open(BytesIO(raw)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"} or getattr(
                    source, "is_animated", False
                ):
                    raise permanent_storage_error(
                        "assets.unsupported_image",
                        "only non-animated JPEG, PNG and WebP images are allowed",
                    )
                source.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                image = source.convert("RGBA" if "A" in source.getbands() else "RGB")
                output = BytesIO()
                image.save(output, format="WEBP", quality=quality, method=6)
                return output.getvalue()
    except StorageError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
    ) as exc:
        raise permanent_storage_error(
            "assets.invalid_image", "image could not be normalized"
        ) from exc


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
            stat = await provider.stat(bucket=intent.bucket, object_key=intent.object_key)
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
            bucket=stat.bucket,
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


class NormalizeContentImageActivity:
    """Second step of the assets-owned content image workflow."""

    def __init__(self, *, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self, uow: UnitOfWork, data: dict[str, Any], activity_ctx: ActivityContext
    ) -> dict[str, Any]:
        del uow, activity_ctx
        workflow = data.get("workflow", {})
        finalized = data.get("state", {}).get(FINALIZE_ACTIVITY_KEY, {})
        asset_id = finalized.get("asset_id")
        if not isinstance(asset_id, str):
            raise KernelError(
                code="assets.content_image_invalid_input",
                category=ErrorCategory.INTERNAL,
                message="content image workflow is missing its finalized source asset",
            )
        try:
            max_edge = int(workflow["max_edge"])
            quality = int(workflow["quality"])
        except (KeyError, TypeError, ValueError) as exc:
            raise KernelError(
                code="assets.content_image_invalid_input",
                category=ErrorCategory.INTERNAL,
                message="content image workflow has an invalid image profile",
            ) from exc
        # The initiating command checked caller permissions. This durable
        # activity runs later without an HTTP principal, so it grants only
        # the internal capability permission needed for the public command.
        result = await NormalizeContentImage(
            replace(self._ctx, permissions=frozenset({PERMISSION_MANAGE}))
        )(uuid.UUID(asset_id), max_edge=max_edge, quality=quality)
        return {
            "asset_id": result.asset.id,
            "public_url": result.public_url,
            "mime_type": result.asset.mime_type,
            "byte_size": result.asset.byte_size,
        }


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
            await provider.delete(bucket=row.bucket, object_key=row.object_key)
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
    content_image_finalize = WorkflowSpec(
        key=CONTENT_IMAGE_FINALIZE_WORKFLOW_KEY,
        version="1",
        activities=(
            ActivitySpec(
                key=FINALIZE_ACTIVITY_KEY,
                timeout_seconds=30.0,
                retry=RetryPolicy(max_attempts=5, base_delay_seconds=1.0),
                handler=FinalizeActivity(ctx=ctx),
            ),
            ActivitySpec(
                key=CONTENT_IMAGE_NORMALIZE_ACTIVITY_KEY,
                timeout_seconds=60.0,
                retry=RetryPolicy(max_attempts=3, base_delay_seconds=1.0),
                handler=NormalizeContentImageActivity(ctx=ctx),
            ),
        ),
    )
    return finalize, delete, content_image_finalize


def register_asset_workflows(registry: WorkflowRegistry, *, ctx: CommandContext) -> None:
    for spec in build_asset_workflow_specs(ctx):
        registry.register(spec)
