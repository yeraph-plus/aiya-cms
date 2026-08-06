"""Settings commands and queries.

Contract source: context/spec/capabilities/settings.md §4.

Updates validate the full value against the registered schema, apply the
optimistic version, and emit the group_updated event in the same
transaction (cache adapters invalidate on that event). Reading a missing
row returns validated code defaults and never writes. No arbitrary
key/value CRUD; unknown fields are rejected by the schema.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from sqlalchemy import select

from inc.capabilities.settings.events import SETTINGS_EVENT_SCHEMAS
from inc.capabilities.settings.groups import SettingGroupRegistry, SettingGroupSpec
from inc.capabilities.settings.models import SettingsValue, SettingsValueData
from inc.capabilities.settings.schemas import (
    PublicSettingsDTO,
    SettingGroupDTO,
    UpdateSettingGroupInput,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"

PERMISSION_READ = "settings.read"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    groups: SettingGroupRegistry
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None


def _forbidden(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.FORBIDDEN, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


def _require_permission(ctx: CommandContext, key: str) -> None:
    if key not in ctx.permissions:
        raise _forbidden("settings.forbidden", f"requires permission {key}")


def _ensure_utc(value: Any) -> Any:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _validate_values(spec: SettingGroupSpec, values: dict[str, Any]) -> dict[str, Any]:
    return spec.value_schema.model_validate(values).model_dump(mode="json")


def _to_dto(row: SettingsValue) -> SettingGroupDTO:
    return SettingGroupDTO(
        group_key=row.group_key,
        schema_version=row.schema_version,
        version=row.version,
        values=dict(row.value.values),
        updated_by=row.updated_by,
        updated_at=_ensure_utc(row.updated_at),
    )


async def _emit_updated(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    spec: SettingGroupSpec,
    row: SettingsValue,
    changed_fields: tuple[str, ...],
) -> None:
    if not spec.emit_events:
        return
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key="settings.group_updated.v1",
            occurred_at=ctx.clock.utc_now(),
            producer="settings",
            aggregate_type="settings",
            aggregate_id=spec.group_key,
            trace_id=ctx.trace_id,
            payload=SETTINGS_EVENT_SCHEMAS["settings.group_updated.v1"]
            .model_validate(
                {
                    "group_key": spec.group_key,
                    "version": row.version,
                    "changed_fields": changed_fields,
                }
            )
            .model_dump(mode="json"),
        ),
    )


async def _append_audit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    action: str,
    group_key: str,
    details: dict[str, Any] | None = None,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=ctx.clock.utc_now(),
            producer="settings",
            aggregate_type="settings",
            aggregate_id=group_key,
            trace_id=ctx.trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": ctx.clock.utc_now().isoformat(),
                "actor_type": "user" if ctx.actor_id else None,
                "actor_id": ctx.actor_id,
                "target_type": "settings",
                "target_id": group_key,
                "trace_id": ctx.trace_id,
                "details": details or {},
            },
        ),
    )


class UpdateSettingGroup:
    """Fully validate, then apply with optimistic version."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, group_key: str, input_: UpdateSettingGroupInput) -> SettingGroupDTO:  # type: ignore[return]
        ctx = self._ctx
        spec = ctx.groups.require(group_key)
        _require_permission(ctx, spec.update_permission)
        values = _validate_values(spec, input_.values)
        async with ctx.uow_factory() as uow:
            row: SettingsValue | None = (
                (
                    await uow.session.execute(
                        select(SettingsValue).where(SettingsValue.group_key == group_key)
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                if input_.expected_version not in (None, 1):
                    raise _conflict(
                        "settings.version_conflict",
                        f"expected version {input_.expected_version}, found none",
                    )
                row = SettingsValue(
                    group_key=group_key,
                    schema_version=spec.version,
                    value=SettingsValueData(schema_version=spec.version, values=values),
                    version=1,
                    updated_by=ctx.actor_id,
                )
                uow.session.add(row)
                changed: tuple[str, ...] = tuple(sorted(values))
            else:
                if input_.expected_version is not None and row.version != input_.expected_version:
                    raise _conflict(
                        "settings.version_conflict",
                        f"expected version {input_.expected_version}, found {row.version}",
                    )
                if row.schema_version != spec.version:
                    raise KernelError(
                        code="settings.schema_mismatch",
                        category=ErrorCategory.CONFLICT,
                        message=(
                            f"stored schema version {row.schema_version} "
                            f"!= registered {spec.version}"
                        ),
                    )
                changed = tuple(
                    field
                    for field in sorted(values)
                    if values[field] != row.value.values.get(field)
                )
                row.value = SettingsValueData(schema_version=spec.version, values=values)
                row.version += 1
                row.updated_by = ctx.actor_id
            await _emit_updated(ctx, uow, spec=spec, row=row, changed_fields=changed)
            await _append_audit(
                ctx,
                uow,
                action="settings.update",
                group_key=group_key,
                details={"changed": list(changed)},
            )
            await uow.commit()
            return _to_dto(row)


class ResetSettingGroup:
    """Explicitly restore code defaults; audited."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, group_key: str) -> SettingGroupDTO:  # type: ignore[return]
        ctx = self._ctx
        spec = ctx.groups.require(group_key)
        _require_permission(ctx, spec.update_permission)
        async with ctx.uow_factory() as uow:
            row: SettingsValue | None = (
                (
                    await uow.session.execute(
                        select(SettingsValue).where(SettingsValue.group_key == group_key)
                    )
                )
                .scalars()
                .first()
            )
            defaults = spec.defaults()
            if row is None:
                row = SettingsValue(
                    group_key=group_key,
                    schema_version=spec.version,
                    value=SettingsValueData(schema_version=spec.version, values=defaults),
                    version=1,
                    updated_by=ctx.actor_id,
                )
                uow.session.add(row)
                changed: tuple[str, ...] = tuple(sorted(defaults))
            else:
                changed = tuple(
                    field
                    for field in sorted(defaults)
                    if defaults[field] != row.value.values.get(field)
                )
                row.value = SettingsValueData(schema_version=spec.version, values=defaults)
                row.version += 1
                row.updated_by = ctx.actor_id
            await _emit_updated(ctx, uow, spec=spec, row=row, changed_fields=changed)
            await _append_audit(
                ctx,
                uow,
                action="settings.reset",
                group_key=group_key,
                details={"changed": list(changed)},
            )
            await uow.commit()
            return _to_dto(row)


class SettingsQueries:
    """Read-only settings surface."""

    def __init__(self, *, uow_factory: UoWFactory, groups: SettingGroupRegistry) -> None:
        self._uow_factory = uow_factory
        self._groups = groups

    async def get_group(self, group_key: str) -> SettingGroupDTO:
        spec = self._groups.require(group_key)
        async with self._uow_factory() as uow:
            row: SettingsValue | None = (
                (
                    await uow.session.execute(
                        select(SettingsValue).where(SettingsValue.group_key == group_key)
                    )
                )
                .scalars()
                .first()
            )
        if row is None:
            return SettingGroupDTO(
                group_key=group_key,
                schema_version=spec.version,
                version=0,
                values=spec.defaults(),
            )
        return _to_dto(row)

    async def list_groups(self) -> list[SettingGroupDTO]:
        groups = [self._groups.require(spec.group_key) for spec in self._groups.specs()]
        return [await self.get_group(spec.group_key) for spec in groups]

    async def get_public_settings(self) -> PublicSettingsDTO:
        """Only fields declared public per group; never sensitive values."""

        values: dict[str, dict[str, Any]] = {}
        for spec in self._groups.specs():
            group = await self.get_group(spec.group_key)
            public = {
                field: group.values[field]
                for field in spec.public_fields
                if field in group.values and field not in spec.sensitive_fields
            }
            values[spec.group_key] = public
        return PublicSettingsDTO(values=values)
