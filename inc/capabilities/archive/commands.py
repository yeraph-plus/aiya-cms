"""Archive semantic Commands and state transitions."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from inc.capabilities.archive.events import ARCHIVE_EVENT_SCHEMAS
from inc.capabilities.archive.models import (
    ArchiveDeliveryAttempt,
    ArchiveDownloadGrant,
    ArchiveExternalLocator,
    ArchiveGrantSnapshot,
    ArchiveItem,
    ArchiveItemSnapshot,
)
from inc.capabilities.archive.ports import (
    ArchiveDeliveryProvider,
    ArchiveProviderError,
    ArchiveSettingsSnapshot,
    ProviderFileFact,
)
from inc.capabilities.archive.schemas import (
    ArchiveDeliveryAttemptDTO,
    ArchiveGrantItemDTO,
    ArchiveItemAdminDTO,
    ArchiveItemDTO,
    ArchiveItemPatchInput,
    ArchiveItemStateInput,
    DownloadGrantDTO,
    GrantStateInput,
    IssueDownloadGrantInput,
    MigrateArchiveItemProviderInput,
    RecordDeliveryAttemptInput,
    RegisterArchiveItemInput,
    VerifyArchiveItemInput,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

PERMISSION_ITEM_READ = "archive.items.read"
PERMISSION_ITEM_MANAGE = "archive.items.manage"
PERMISSION_ITEM_VERIFY = "archive.items.verify"
PERMISSION_GRANT_READ = "archive.grants.read"
PERMISSION_GRANT_ISSUE = "archive.grants.issue"
PERMISSION_GRANT_ACTIVATE = "archive.grants.activate"
PERMISSION_GRANT_REVOKE = "archive.grants.revoke"
PERMISSION_DELIVERY = "archive.delivery.resolve"

# Names kept short for code that follows the other capability command modules.
PERMISSION_READ = PERMISSION_ITEM_READ
PERMISSION_MANAGE = PERMISSION_ITEM_MANAGE


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter | None
    providers: Mapping[str, ArchiveDeliveryProvider]
    provider_settings: Mapping[str, ArchiveSettingsSnapshot | Mapping[str, Any]] = field(
        default_factory=dict
    )
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None


ArchiveCommandContext = CommandContext


def _forbidden(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.FORBIDDEN, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


def _validation(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


def _not_found(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.NOT_FOUND, message=message)


def _require(ctx: CommandContext, permission: str) -> None:
    if permission not in ctx.permissions:
        raise _forbidden("archive.forbidden", f"requires permission {permission}")


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _required_utc(value: datetime) -> datetime:
    return cast(datetime, _utc(value))


def _uuid(value: Any, *, code: str, label: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _not_found(code, f"{label} {value}") from exc


def _provider(ctx: CommandContext, provider_key: str) -> ArchiveDeliveryProvider:
    provider = ctx.providers.get(provider_key)
    if provider is None:
        raise _validation(
            "archive.unknown_provider", f"provider {provider_key!r} is not configured"
        )
    return provider


def _settings(ctx: CommandContext, provider_key: str) -> ArchiveSettingsSnapshot:
    value = ctx.provider_settings.get(provider_key)
    if isinstance(value, ArchiveSettingsSnapshot):
        return value
    if isinstance(value, Mapping):
        return ArchiveSettingsSnapshot(values=dict(value))
    return ArchiveSettingsSnapshot()


def _locator(value: Any) -> ArchiveExternalLocator:
    if isinstance(value, ArchiveExternalLocator):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return ArchiveExternalLocator.model_validate(value)


def _locator_digest(locator: ArchiveExternalLocator) -> str:
    encoded = json.dumps(
        locator.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _locator_kind(locator: ArchiveExternalLocator) -> str:
    # The row owns the provider key; this is only an admin-safe display hint.
    value = locator.value
    if value.startswith("/"):
        return "path"
    if "/" in value:
        return "reference"
    return "opaque"


def _item_dto(row: ArchiveItem) -> ArchiveItemDTO:
    return ArchiveItemDTO(
        id=str(row.id),
        item_key=row.item_key,
        display_name=row.display_name,
        size_bytes=row.size_bytes,
        part_number=row.part_number,
        checksum_algorithm=row.checksum_algorithm,
        checksum_value=row.checksum_value,
        state=row.state,  # type: ignore[arg-type]
        version=row.version,
        created_at=_required_utc(row.created_at),
        updated_at=_required_utc(row.updated_at),
    )


def _item_admin_dto(row: ArchiveItem) -> ArchiveItemAdminDTO:
    return ArchiveItemAdminDTO(
        **_item_dto(row).model_dump(),
        provider_key=row.provider_key,
        provider_contract_version=row.provider_contract_version,
        provider_fact_version=row.provider_fact_version,
        last_verified_at=_utc(row.last_verified_at),
        unavailable_reason=row.unavailable_reason,
        locator_digest=_locator_digest(row.external_locator),
        locator_kind=_locator_kind(row.external_locator),
    )


def _grant_item_dto(item: ArchiveItemSnapshot) -> ArchiveGrantItemDTO:
    return ArchiveGrantItemDTO(
        item_id=item.item_id,
        item_key=item.item_key,
        version=item.version,
        part_number=item.part_number,
        display_name=item.display_name,
        size_bytes=item.size_bytes,
        checksum_algorithm=item.checksum_algorithm,
        checksum_value=item.checksum_value,
    )


def _grant_dto(row: ArchiveDownloadGrant) -> DownloadGrantDTO:
    return DownloadGrantDTO(
        id=str(row.id),
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        product_ref=row.product_ref,
        quote_ref=row.quote_ref,
        points_entry_ref=row.points_entry_ref,
        target_type=row.target_type,
        target_id=row.target_id,
        manifest_version=row.manifest_version,
        manifest_digest=row.manifest_digest,
        items=[_grant_item_dto(item) for item in row.item_snapshot.items],
        status=row.status,  # type: ignore[arg-type]
        valid_from=_required_utc(row.valid_from),
        expires_at=_required_utc(row.expires_at),
        version=row.version,
        created_at=_required_utc(row.created_at),
        updated_at=_required_utc(row.updated_at),
    )


def _attempt_dto(row: ArchiveDeliveryAttempt) -> ArchiveDeliveryAttemptDTO:
    return ArchiveDeliveryAttemptDTO(
        id=str(row.id),
        grant_id=str(row.grant_id),
        item_id=str(row.item_id),
        provider_key=row.provider_key,
        attempt_number=row.attempt_number,
        status=row.status,  # type: ignore[arg-type]
        reason_code=row.reason_code,
        provider_delivery_ref=row.provider_delivery_ref,
        link_expires_at=_utc(row.link_expires_at),
        started_at=_required_utc(row.started_at),
        completed_at=_utc(row.completed_at),
    )


async def _emit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    key: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> None:
    if ctx.outbox is None:
        return
    schema = ARCHIVE_EVENT_SCHEMAS[key]
    safe_payload = schema.model_validate(payload).model_dump(mode="json")
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=key,
            occurred_at=ctx.clock.utc_now(),
            producer="archive",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            trace_id=ctx.trace_id,
            payload=safe_payload,
        ),
    )


def _check_version(row: Any, expected_version: int | None) -> None:
    if expected_version is not None and row.version != expected_version:
        raise _conflict(
            "archive.version_conflict",
            f"expected version {expected_version}, current version is {row.version}",
        )


def _item_event_payload(row: ArchiveItem) -> dict[str, Any]:
    return {
        "item_id": str(row.id),
        "item_key": row.item_key,
        "provider_key": row.provider_key,
        "state": row.state,
        "version": row.version,
    }


def _grant_event_payload(row: ArchiveDownloadGrant) -> dict[str, Any]:
    return {
        "grant_id": str(row.id),
        "status": row.status,
        "manifest_version": row.manifest_version,
        "manifest_digest": row.manifest_digest,
    }


def _manifest_digest(items: list[ArchiveItem]) -> str:
    values = [
        {
            "item_id": str(item.id),
            "item_key": item.item_key,
            "version": item.version,
            "part_number": item.part_number,
            "size_bytes": item.size_bytes,
            "checksum_algorithm": item.checksum_algorithm,
            "checksum_value": item.checksum_value,
        }
        for item in sorted(items, key=lambda row: (row.part_number, str(row.id)))
    ]
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def compute_manifest_digest(items: list[ArchiveItem]) -> str:
    """Compute the archive-owned digest for a manifest item snapshot."""

    return _manifest_digest(items)


def _input_or_state(value: Any, model: type[Any]) -> Any:
    return model.model_validate(value) if isinstance(value, dict) else value


class RegisterArchiveItem:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: RegisterArchiveItemInput) -> ArchiveItemAdminDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_ITEM_MANAGE)
        provider = _provider(ctx, input_.provider_key)
        del provider  # registration is intentionally provider-neutral/no network
        locator = _locator(input_.external_locator)
        async with ctx.uow_factory() as uow:
            existing = (
                (
                    await uow.session.execute(
                        select(ArchiveItem).where(ArchiveItem.item_key == input_.item_key)
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                raise _conflict("archive.item_already_registered", "item_key is already registered")
            row = ArchiveItem(
                item_key=input_.item_key,
                provider_key=input_.provider_key,
                provider_contract_version=input_.provider_contract_version,
                external_locator=locator,
                display_name=input_.display_name,
                size_bytes=input_.size_bytes,
                checksum_algorithm=input_.checksum_algorithm,
                checksum_value=input_.checksum_value,
                part_number=input_.part_number,
                state="pending",
                version=1,
            )
            uow.session.add(row)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                raise _conflict(
                    "archive.item_already_registered", "item_key is already registered"
                ) from exc
            await _emit(
                ctx,
                uow,
                key="archive.item_registered.v1",
                aggregate_type="archive_item",
                aggregate_id=str(row.id),
                payload=_item_event_payload(row),
            )
            await uow.commit()
            return _item_admin_dto(row)
        raise AssertionError("unreachable: register archive item completed")


class UpdateArchiveItem:
    """Update public metadata before activation and require fresh verification."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, item_id: Any, input_: ArchiveItemPatchInput) -> ArchiveItemAdminDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_ITEM_MANAGE)
        parsed = _uuid(item_id, code="archive.item_not_found", label="item")
        async with ctx.uow_factory() as uow:
            row: ArchiveItem | None = await uow.session.get(ArchiveItem, parsed)
            if row is None:
                raise _not_found("archive.item_not_found", f"item {item_id}")
            _check_version(row, input_.expected_version)
            if row.state in {"active", "retired"}:
                raise _conflict("archive.item_not_mutable", f"item is {row.state}")
            values = input_.model_dump(exclude_unset=True, exclude={"expected_version"})
            for name, value in values.items():
                setattr(row, name, value)
            row.state = "pending"
            row.last_verified_at = None
            row.provider_fact_version = None
            row.unavailable_reason = None
            row.version += 1
            await uow.commit()
            return _item_admin_dto(row)
        raise AssertionError("unreachable: update archive item completed")


class VerifyArchiveItem:
    """Explicitly stat the bound provider and persist only safe facts."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self,
        item: VerifyArchiveItemInput | str | uuid.UUID,
        *,
        expected_version: int | None = None,
    ) -> ArchiveItemAdminDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_ITEM_VERIFY)
        input_ = (
            _input_or_state(item, VerifyArchiveItemInput)
            if not isinstance(item, (str, uuid.UUID))
            else VerifyArchiveItemInput(item_id=str(item), expected_version=expected_version)
        )
        item_id = _uuid(input_.item_id, code="archive.item_not_found", label="item")
        async with ctx.uow_factory() as uow:
            row: ArchiveItem | None = await uow.session.get(ArchiveItem, item_id)
            if row is None:
                raise _not_found("archive.item_not_found", f"item {input_.item_id}")
            _check_version(row, input_.expected_version)
            if row.state == "retired":
                raise _conflict("archive.item_retired", "retired item cannot be verified")
            provider_key = row.provider_key
            locator = row.external_locator
            contract_version = row.provider_contract_version

        provider = _provider(ctx, provider_key)
        try:
            fact = await provider.stat(
                external_locator=locator,
                settings_snapshot=_settings(ctx, provider_key),
            )
        except ArchiveProviderError as exc:
            fact = ProviderFileFact(status="unavailable", reason_code=exc.reason_code)
        except Exception as exc:  # noqa: BLE001 - provider details never cross the boundary
            del exc
            fact = ProviderFileFact(status="unavailable", reason_code="provider_unavailable")

        async with ctx.uow_factory() as uow:
            row = await uow.session.get(ArchiveItem, item_id)
            if row is None:
                raise _not_found("archive.item_not_found", f"item {input_.item_id}")
            _check_version(row, input_.expected_version)
            if row.state == "retired":
                raise _conflict("archive.item_retired", "retired item cannot be verified")
            if not fact.available:
                transient_reasons = {
                    "timeout",
                    "rate_limited",
                    "provider_unavailable",
                    "archive.provider_unavailable",
                }
                if (fact.reason_code or "provider_unavailable") in transient_reasons:
                    # A transient provider failure is not evidence that the
                    # item itself is unavailable.
                    return _item_admin_dto(row)
                row.state = "unavailable"
                row.unavailable_reason = fact.reason_code or "provider_unavailable"
                row.version += 1
                await _emit(
                    ctx,
                    uow,
                    key="archive.item_unavailable.v1",
                    aggregate_type="archive_item",
                    aggregate_id=str(row.id),
                    payload=_item_event_payload(row),
                )
                await uow.commit()
                return _item_admin_dto(row)
            if fact.size_bytes != row.size_bytes:
                row.state = "unavailable"
                row.unavailable_reason = "manifest_mismatch"
                row.version += 1
                await _emit(
                    ctx,
                    uow,
                    key="archive.item_unavailable.v1",
                    aggregate_type="archive_item",
                    aggregate_id=str(row.id),
                    payload=_item_event_payload(row),
                )
                await uow.commit()
                raise _conflict(
                    "archive.manifest_mismatch", "provider file size does not match archive item"
                )
            if row.checksum_value is not None and fact.checksum_value is not None:
                if row.checksum_value != fact.checksum_value:
                    row.state = "unavailable"
                    row.unavailable_reason = "manifest_mismatch"
                    row.version += 1
                    await _emit(
                        ctx,
                        uow,
                        key="archive.item_unavailable.v1",
                        aggregate_type="archive_item",
                        aggregate_id=str(row.id),
                        payload=_item_event_payload(row),
                    )
                    await uow.commit()
                    raise _conflict(
                        "archive.manifest_mismatch", "provider checksum does not match archive item"
                    )
            row.provider_fact_version = fact.provider_fact_version or contract_version
            row.last_verified_at = ctx.clock.utc_now()
            row.unavailable_reason = None
            if row.state == "unavailable":
                row.state = "pending"
            row.version += 1
            await uow.commit()
            return _item_admin_dto(row)
        raise AssertionError("unreachable: verify archive item completed")


class ActivateArchiveItem:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self,
        item: ArchiveItemStateInput | str | uuid.UUID,
        *,
        expected_version: int | None = None,
    ) -> ArchiveItemAdminDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_ITEM_MANAGE)
        input_ = (
            _input_or_state(item, ArchiveItemStateInput)
            if not isinstance(item, (str, uuid.UUID))
            else ArchiveItemStateInput(item_id=str(item), expected_version=expected_version)
        )
        item_id = _uuid(input_.item_id, code="archive.item_not_found", label="item")
        async with ctx.uow_factory() as uow:
            row: ArchiveItem | None = await uow.session.get(ArchiveItem, item_id)
            if row is None:
                raise _not_found("archive.item_not_found", f"item {input_.item_id}")
            _check_version(row, input_.expected_version)
            if row.state == "active":
                return _item_admin_dto(row)
            if row.state == "retired":
                raise _conflict("archive.item_retired", "retired item cannot be activated")
            if row.state != "pending" or row.last_verified_at is None:
                raise _conflict(
                    "archive.item_not_verified", "item must be successfully verified first"
                )
            row.state = "active"
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="archive.item_activated.v1",
                aggregate_type="archive_item",
                aggregate_id=str(row.id),
                payload=_item_event_payload(row),
            )
            await uow.commit()
            return _item_admin_dto(row)
        raise AssertionError("unreachable: activate archive item completed")


class MarkArchiveItemUnavailable:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self,
        item: ArchiveItemStateInput | str | uuid.UUID,
        *,
        reason: str | None = None,
        expected_version: int | None = None,
    ) -> ArchiveItemAdminDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_ITEM_MANAGE)
        input_ = (
            _input_or_state(item, ArchiveItemStateInput)
            if not isinstance(item, (str, uuid.UUID))
            else ArchiveItemStateInput(
                item_id=str(item), expected_version=expected_version, reason=reason
            )
        )
        item_id = _uuid(input_.item_id, code="archive.item_not_found", label="item")
        async with ctx.uow_factory() as uow:
            row: ArchiveItem | None = await uow.session.get(ArchiveItem, item_id)
            if row is None:
                raise _not_found("archive.item_not_found", f"item {input_.item_id}")
            _check_version(row, input_.expected_version)
            if row.state == "retired":
                raise _conflict("archive.item_retired", "retired item cannot be made unavailable")
            if row.state == "unavailable":
                return _item_admin_dto(row)
            row.state = "unavailable"
            row.unavailable_reason = input_.reason or "manual_unavailable"
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="archive.item_unavailable.v1",
                aggregate_type="archive_item",
                aggregate_id=str(row.id),
                payload=_item_event_payload(row),
            )
            await uow.commit()
            return _item_admin_dto(row)
        raise AssertionError("unreachable: mark archive item unavailable completed")


class RetireArchiveItem:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self,
        item: ArchiveItemStateInput | str | uuid.UUID,
        *,
        expected_version: int | None = None,
        reason: str | None = None,
    ) -> ArchiveItemAdminDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_ITEM_MANAGE)
        input_ = (
            _input_or_state(item, ArchiveItemStateInput)
            if not isinstance(item, (str, uuid.UUID))
            else ArchiveItemStateInput(
                item_id=str(item), expected_version=expected_version, reason=reason
            )
        )
        item_id = _uuid(input_.item_id, code="archive.item_not_found", label="item")
        async with ctx.uow_factory() as uow:
            row: ArchiveItem | None = await uow.session.get(ArchiveItem, item_id)
            if row is None:
                raise _not_found("archive.item_not_found", f"item {input_.item_id}")
            _check_version(row, input_.expected_version)
            if row.state == "retired":
                return _item_admin_dto(row)
            row.state = "retired"
            row.unavailable_reason = input_.reason or "retired"
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="archive.item_retired.v1",
                aggregate_type="archive_item",
                aggregate_id=str(row.id),
                payload=_item_event_payload(row),
            )
            await uow.commit()
            return _item_admin_dto(row)
        raise AssertionError("unreachable: retire archive item completed")


class MigrateArchiveItemProvider:
    """Create a new provider snapshot; the old locator is never reinterpreted."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: MigrateArchiveItemProviderInput) -> ArchiveItemAdminDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_ITEM_MANAGE)
        item_id = _uuid(input_.item_id, code="archive.item_not_found", label="item")
        locator = _locator(input_.external_locator)
        provider = _provider(ctx, input_.provider_key)
        async with ctx.uow_factory() as uow:
            old: ArchiveItem | None = await uow.session.get(ArchiveItem, item_id)
            if old is None:
                raise _not_found("archive.item_not_found", f"item {input_.item_id}")
            _check_version(old, input_.expected_version)
            if old.state == "retired":
                raise _conflict("archive.item_retired", "retired item cannot be migrated")
            size_bytes = old.size_bytes
            checksum_value = old.checksum_value
            checksum_algorithm = old.checksum_algorithm
            display_name = old.display_name

        try:
            fact = await provider.stat(
                external_locator=locator,
                settings_snapshot=_settings(ctx, input_.provider_key),
            )
        except ArchiveProviderError as exc:
            raise _conflict(
                "archive.provider_unavailable", "new provider could not verify item"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - provider details never cross the boundary
            del exc
            raise _conflict(
                "archive.provider_unavailable", "new provider could not verify item"
            ) from None
        if not fact.available:
            raise _conflict("archive.provider_unavailable", "new provider could not verify item")
        if fact.size_bytes != size_bytes:
            raise _conflict(
                "archive.manifest_mismatch", "new provider file size does not match item"
            )
        if checksum_value is not None and fact.checksum_value is not None:
            if checksum_value != fact.checksum_value:
                raise _conflict(
                    "archive.manifest_mismatch", "new provider checksum does not match item"
                )

        async with ctx.uow_factory() as uow:
            row = await uow.session.get(ArchiveItem, item_id)
            if row is None:
                raise _not_found("archive.item_not_found", f"item {input_.item_id}")
            _check_version(row, input_.expected_version)
            row.provider_key = input_.provider_key
            row.provider_contract_version = input_.provider_contract_version
            row.external_locator = locator
            row.display_name = display_name
            row.checksum_algorithm = checksum_algorithm
            row.checksum_value = checksum_value
            row.provider_fact_version = (
                fact.provider_fact_version or input_.provider_contract_version
            )
            row.last_verified_at = ctx.clock.utc_now()
            row.state = "pending"
            row.unavailable_reason = None
            row.version += 1
            await uow.commit()
            return _item_admin_dto(row)
        raise AssertionError("unreachable: migrate archive item provider completed")


class IssueDownloadGrant:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: IssueDownloadGrantInput) -> DownloadGrantDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_GRANT_ISSUE)
        now = ctx.clock.utc_now()
        valid_from = _required_utc(input_.valid_from) if input_.valid_from else now
        expires_at = _required_utc(input_.expires_at)
        business_ref = input_.business_consumption_ref or input_.idempotency_key
        digest = hashlib.sha256(business_ref.encode("utf-8")).hexdigest()
        async with ctx.uow_factory() as uow:
            existing: ArchiveDownloadGrant | None = (
                (
                    await uow.session.execute(
                        select(ArchiveDownloadGrant).where(
                            ArchiveDownloadGrant.idempotency_key_digest == digest
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                if (
                    existing.subject_type != input_.subject_type
                    or existing.subject_id != input_.subject_id
                ):
                    raise _conflict(
                        "archive.grant_forbidden", "consumption key belongs to another subject"
                    )
                if existing.manifest_version != input_.manifest_version:
                    raise _conflict(
                        "archive.manifest_mismatch", "consumption key has a different manifest"
                    )
                return _grant_dto(existing)
            if expires_at <= valid_from or expires_at <= now:
                raise _validation(
                    "archive.invalid_grant_window", "grant expiry must be in the future"
                )
            item_ids = [
                _uuid(value, code="archive.item_not_found", label="item")
                for value in input_.item_ids
            ]
            rows = (
                (await uow.session.execute(select(ArchiveItem).where(ArchiveItem.id.in_(item_ids))))
                .scalars()
                .all()
            )
            by_id = {row.id: row for row in rows}
            if len(by_id) != len(item_ids):
                raise _not_found("archive.item_not_found", "one or more grant items do not exist")
            ordered = [by_id[item_id] for item_id in item_ids]
            if any(row.state != "active" for row in ordered):
                raise _conflict("archive.item_not_deliverable", "grant items must all be active")
            part_numbers = [row.part_number for row in ordered]
            if len(part_numbers) != len(set(part_numbers)):
                raise _validation("archive.manifest_mismatch", "part_number must be unique")
            computed_digest = _manifest_digest(ordered)
            manifest_digest = input_.manifest_digest or computed_digest
            if (
                len(manifest_digest) == 64
                and all(character in "0123456789abcdef" for character in manifest_digest)
                and manifest_digest != computed_digest
            ):
                raise _conflict("archive.manifest_mismatch", "manifest digest does not match items")
            snapshot = ArchiveGrantSnapshot(
                manifest_version=input_.manifest_version,
                manifest_digest=manifest_digest,
                items=tuple(
                    ArchiveItemSnapshot(
                        item_id=str(row.id),
                        item_key=row.item_key,
                        version=row.version,
                        provider_key=row.provider_key,
                        part_number=row.part_number,
                        display_name=row.display_name,
                        size_bytes=row.size_bytes,
                        checksum_algorithm=row.checksum_algorithm,
                        checksum_value=row.checksum_value,
                    )
                    for row in sorted(ordered, key=lambda item: (item.part_number, str(item.id)))
                ),
            )
            grant = ArchiveDownloadGrant(
                subject_type=input_.subject_type,
                subject_id=input_.subject_id,
                product_ref=input_.product_ref,
                quote_ref=input_.quote_ref,
                points_entry_ref=input_.points_entry_ref,
                target_type=input_.target_type,
                target_id=input_.target_id,
                manifest_version=input_.manifest_version,
                manifest_digest=manifest_digest,
                item_snapshot=snapshot,
                status="pending",
                valid_from=valid_from,
                expires_at=expires_at,
                idempotency_key_digest=digest,
                version=1,
            )
            uow.session.add(grant)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                await uow.rollback()
                async with ctx.uow_factory() as retry_uow:
                    existing = (
                        (
                            await retry_uow.session.execute(
                                select(ArchiveDownloadGrant).where(
                                    ArchiveDownloadGrant.idempotency_key_digest == digest
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if existing is not None:
                        return _grant_dto(existing)
                raise _conflict(
                    "archive.grant_duplicate", "grant consumption already exists"
                ) from exc
            await _emit(
                ctx,
                uow,
                key="archive.grant_issued.v1",
                aggregate_type="archive_grant",
                aggregate_id=str(grant.id),
                payload=_grant_event_payload(grant),
            )
            await uow.commit()
            return _grant_dto(grant)
        raise AssertionError("unreachable: issue download grant completed")


class ActivateDownloadGrant:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self,
        grant: GrantStateInput | str | uuid.UUID,
        *,
        expected_version: int | None = None,
    ) -> DownloadGrantDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_GRANT_ACTIVATE)
        input_ = (
            _input_or_state(grant, GrantStateInput)
            if not isinstance(grant, (str, uuid.UUID))
            else GrantStateInput(grant_id=str(grant), expected_version=expected_version)
        )
        grant_id = _uuid(input_.grant_id, code="archive.grant_not_found", label="grant")
        async with ctx.uow_factory() as uow:
            row: ArchiveDownloadGrant | None = await uow.session.get(ArchiveDownloadGrant, grant_id)
            if row is None:
                raise _not_found("archive.grant_not_found", f"grant {input_.grant_id}")
            _check_version(row, input_.expected_version)
            if row.status == "active":
                return _grant_dto(row)
            if row.status != "pending":
                raise _conflict("archive.grant_not_activatable", f"grant is {row.status}")
            now = ctx.clock.utc_now()
            if _required_utc(row.expires_at) <= now:
                row.status = "expired"
                row.version += 1
                await uow.commit()
                raise _conflict("archive.grant_expired", "grant has expired")
            if _required_utc(row.valid_from) > now:
                raise _conflict(
                    "archive.grant_not_yet_valid", "grant validity window has not started"
                )
            row.status = "active"
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="archive.grant_activated.v1",
                aggregate_type="archive_grant",
                aggregate_id=str(row.id),
                payload=_grant_event_payload(row),
            )
            await uow.commit()
            return _grant_dto(row)
        raise AssertionError("unreachable: activate download grant completed")


class ExpireDownloadGrant:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self,
        grant: GrantStateInput | str | uuid.UUID,
        *,
        expected_version: int | None = None,
    ) -> DownloadGrantDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_GRANT_ACTIVATE)
        input_ = (
            _input_or_state(grant, GrantStateInput)
            if not isinstance(grant, (str, uuid.UUID))
            else GrantStateInput(grant_id=str(grant), expected_version=expected_version)
        )
        grant_id = _uuid(input_.grant_id, code="archive.grant_not_found", label="grant")
        async with ctx.uow_factory() as uow:
            row: ArchiveDownloadGrant | None = await uow.session.get(ArchiveDownloadGrant, grant_id)
            if row is None:
                raise _not_found("archive.grant_not_found", f"grant {input_.grant_id}")
            _check_version(row, input_.expected_version)
            if row.status == "expired":
                return _grant_dto(row)
            if row.status in {"revoked", "failed"}:
                raise _conflict("archive.grant_not_expirable", f"grant is {row.status}")
            if _required_utc(row.expires_at) > ctx.clock.utc_now():
                raise _conflict("archive.grant_not_expired", "grant has not expired")
            row.status = "expired"
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="archive.grant_expired.v1",
                aggregate_type="archive_grant",
                aggregate_id=str(row.id),
                payload=_grant_event_payload(row),
            )
            await uow.commit()
            return _grant_dto(row)
        raise AssertionError("unreachable: expire download grant completed")


class RevokeDownloadGrant:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self,
        grant: GrantStateInput | str | uuid.UUID,
        *,
        expected_version: int | None = None,
        reason: str | None = None,
    ) -> DownloadGrantDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_GRANT_REVOKE)
        input_ = (
            _input_or_state(grant, GrantStateInput)
            if not isinstance(grant, (str, uuid.UUID))
            else GrantStateInput(
                grant_id=str(grant), expected_version=expected_version, reason=reason
            )
        )
        grant_id = _uuid(input_.grant_id, code="archive.grant_not_found", label="grant")
        async with ctx.uow_factory() as uow:
            row: ArchiveDownloadGrant | None = await uow.session.get(ArchiveDownloadGrant, grant_id)
            if row is None:
                raise _not_found("archive.grant_not_found", f"grant {input_.grant_id}")
            _check_version(row, input_.expected_version)
            if row.status == "revoked":
                return _grant_dto(row)
            if row.status not in {"pending", "active"}:
                raise _conflict("archive.grant_not_revocable", f"grant is {row.status}")
            row.status = "revoked"
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="archive.grant_revoked.v1",
                aggregate_type="archive_grant",
                aggregate_id=str(row.id),
                payload=_grant_event_payload(row),
            )
            await uow.commit()
            return _grant_dto(row)
        raise AssertionError("unreachable: revoke download grant completed")


class RecordDeliveryAttempt:
    """Persist safe delivery facts; raw provider responses never enter this row."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: RecordDeliveryAttemptInput) -> ArchiveDeliveryAttemptDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_DELIVERY)
        grant_id = _uuid(input_.grant_id, code="archive.grant_not_found", label="grant")
        item_id = _uuid(input_.item_id, code="archive.item_not_found", label="item")
        async with ctx.uow_factory() as uow:
            grant = await uow.session.get(ArchiveDownloadGrant, grant_id)
            if grant is None:
                raise _not_found("archive.grant_not_found", f"grant {input_.grant_id}")
            snapshot_item = next(
                (item for item in grant.item_snapshot.items if item.item_id == str(item_id)),
                None,
            )
            if snapshot_item is None:
                raise _conflict("archive.item_not_deliverable", "item is not part of the grant")
            if snapshot_item.provider_key != input_.provider_key:
                raise _conflict(
                    "archive.manifest_mismatch", "provider does not match grant snapshot"
                )
            existing: ArchiveDeliveryAttempt | None = (
                (
                    await uow.session.execute(
                        select(ArchiveDeliveryAttempt).where(
                            ArchiveDeliveryAttempt.grant_id == grant_id,
                            ArchiveDeliveryAttempt.item_id == item_id,
                            ArchiveDeliveryAttempt.attempt_number == input_.attempt_number,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                return _attempt_dto(existing)
            started_at = (
                _required_utc(input_.started_at) if input_.started_at else ctx.clock.utc_now()
            )
            row = ArchiveDeliveryAttempt(
                grant_id=grant_id,
                item_id=item_id,
                provider_key=input_.provider_key,
                attempt_number=input_.attempt_number,
                status=input_.status,
                reason_code=input_.reason_code,
                provider_delivery_ref=input_.provider_delivery_ref,
                link_expires_at=_utc(input_.link_expires_at),
                started_at=started_at,
                completed_at=_utc(input_.completed_at),
            )
            uow.session.add(row)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                await uow.rollback()
                async with ctx.uow_factory() as retry_uow:
                    existing = (
                        (
                            await retry_uow.session.execute(
                                select(ArchiveDeliveryAttempt).where(
                                    ArchiveDeliveryAttempt.grant_id == grant_id,
                                    ArchiveDeliveryAttempt.item_id == item_id,
                                    ArchiveDeliveryAttempt.attempt_number == input_.attempt_number,
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if existing is not None:
                        return _attempt_dto(existing)
                raise _conflict(
                    "archive.delivery_attempt_duplicate", "delivery attempt already exists"
                ) from exc
            await uow.commit()
            return _attempt_dto(row)
        raise AssertionError("unreachable: record delivery attempt completed")


# Compatibility aliases for callers using the item/grant aggregate names.
ActivateItem = ActivateArchiveItem
VerifyItem = VerifyArchiveItem
RetireItem = RetireArchiveItem
IssueGrant = IssueDownloadGrant
ActivateGrant = ActivateDownloadGrant
ExpireGrant = ExpireDownloadGrant
RevokeGrant = RevokeDownloadGrant
