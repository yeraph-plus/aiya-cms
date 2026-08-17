"""Settings commands and queries.

Contract source: context/spec/capabilities/settings.md §3/§4/§5.

The database stores one row per field, while commands load and write a whole
group in one transaction.  Missing rows are completed from registered Field
defaults and reads never initialize the database.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pydantic import SecretStr, TypeAdapter
from sqlalchemy import func, select

from inc.capabilities.settings.events import SETTINGS_EVENT_SCHEMAS
from inc.capabilities.settings.groups import SettingGroupRegistry, SettingGroupSpec
from inc.capabilities.settings.models import SettingsValue, SettingValuePayload
from inc.capabilities.settings.schemas import (
    PublicSettingsDTO,
    SettingFieldDTO,
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
    """Allow the general update key to cover every settings group."""

    if key in ctx.permissions:
        return
    if (
        key.endswith(".update")
        and key.startswith("settings.")
        and "settings.update" in ctx.permissions
    ):
        return
    raise _forbidden("settings.forbidden", f"requires permission {key}")


def _require_group(ctx: CommandContext, group_key: str) -> SettingGroupSpec:
    try:
        return ctx.groups.require(group_key)
    except KernelError as exc:
        if exc.code == "settings.unknown_group":
            raise KernelError(
                code="settings.unknown_group",
                category=ErrorCategory.VALIDATION,
                message=exc.message,
            ) from exc
        raise


def _require_query_group(groups: SettingGroupRegistry, group_key: str) -> SettingGroupSpec:
    try:
        return groups.require(group_key)
    except KernelError as exc:
        if exc.code == "settings.unknown_group":
            raise KernelError(
                code="settings.unknown_group",
                category=ErrorCategory.VALIDATION,
                message=exc.message,
            ) from exc
        raise


def _json_normalize(value: Any) -> Any:
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if isinstance(value, dict):
        value = {key: _json_normalize(item) for key, item in value.items()}
    elif isinstance(value, (list, tuple)):
        value = [_json_normalize(item) for item in value]
    return json.loads(json.dumps(value, default=str))


def _validate_values(spec: SettingGroupSpec, values: dict[str, Any]) -> dict[str, Any]:
    model = spec.value_schema.model_validate(values)
    dumped = model.model_dump()
    normalized = _json_normalize(dumped)
    if not isinstance(normalized, dict):
        raise TypeError(f"settings group {spec.group_key} schema did not produce an object")
    return normalized


def _field_dtos(spec: SettingGroupSpec) -> tuple[SettingFieldDTO, ...]:
    defaults = spec.defaults()
    return tuple(
        SettingFieldDTO(
            slug=field.slug,
            type=field.type,
            type_sub=field.type_sub,
            default=defaults[field.slug],
            metadata=field.metadata.model_dump(mode="json"),
            public=field.public,
            sensitive=field.sensitive,
        )
        for field in spec.fields
    )


def _ensure_utc(value: Any) -> Any:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _group_version(rows: list[SettingsValue]) -> int:
    versions = {row.group_version for row in rows}
    if len(versions) > 1:
        raise KernelError(
            code="settings.inconsistent_group_version",
            category=ErrorCategory.INTERNAL,
            message="settings rows in one group have different versions",
        )
    return next(iter(versions), 0)


def _check_rows(spec: SettingGroupSpec, rows: list[SettingsValue]) -> None:
    for row in rows:
        if row.field_slug not in {field.slug for field in spec.fields}:
            raise KernelError(
                code="settings.unknown_field",
                category=ErrorCategory.CONFLICT,
                message=f"stored field {row.field_slug!r} is not registered in {spec.group_key!r}",
            )
        if row.schema_version != spec.version:
            raise KernelError(
                code="settings.schema_mismatch",
                category=ErrorCategory.CONFLICT,
                message=(
                    f"stored schema version {row.schema_version} != registered {spec.version}"
                ),
            )


def _effective_values(spec: SettingGroupSpec, rows: list[SettingsValue]) -> dict[str, Any]:
    _check_rows(spec, rows)
    values = spec.defaults()
    for row in rows:
        values[row.field_slug] = row.value.value
    return _validate_values(spec, values)


def _updated_metadata(rows: list[SettingsValue]) -> tuple[str | None, Any | None]:
    if not rows:
        return None, None
    latest = max(rows, key=lambda row: row.updated_at)
    return latest.updated_by, _ensure_utc(latest.updated_at)


def _to_dto(
    spec: SettingGroupSpec,
    *,
    values: dict[str, Any],
    version: int,
    updated_by: str | None = None,
    updated_at: Any | None = None,
) -> SettingGroupDTO:
    return SettingGroupDTO(
        group_key=spec.group_key,
        schema_version=spec.version,
        version=version,
        fields=_field_dtos(spec),
        values=values,
        sensitive_configured={
            slug: values.get(slug) not in (None, "") for slug in spec.sensitive_fields
        },
        updated_by=updated_by,
        updated_at=updated_at,
    )


def redact_sensitive_group(group: SettingGroupDTO) -> SettingGroupDTO:
    """Return the management HTTP projection without write-only secrets."""

    sensitive = {field.slug for field in group.fields if field.sensitive}
    if not sensitive:
        return group
    return group.model_copy(
        update={
            "values": {slug: value for slug, value in group.values.items() if slug not in sensitive}
        }
    )


def _merged_update_values(
    spec: SettingGroupSpec,
    current: dict[str, Any],
    input_: UpdateSettingGroupInput,
) -> dict[str, Any]:
    clears = set(input_.clear_sensitive_fields or ())
    sensitive = set(spec.sensitive_fields)
    invalid = clears - sensitive
    conflicts = clears & set(input_.values)
    if invalid or conflicts:
        details: list[str] = []
        if invalid:
            details.append(f"not sensitive: {sorted(invalid)}")
        if conflicts:
            details.append(f"set and clear: {sorted(conflicts)}")
        raise KernelError(
            code="settings.invalid_sensitive_clear",
            category=ErrorCategory.VALIDATION,
            message="invalid sensitive field clear request",
            details={"reason": "; ".join(details)},
        )
    merged = {**current, **input_.values}
    for slug in clears:
        merged[slug] = None
    return merged


async def _load_group_rows(
    uow: UnitOfWork, group_key: str, *, lock: bool = False
) -> list[SettingsValue]:
    query = select(SettingsValue).where(SettingsValue.group_key == group_key)
    if lock:
        query = query.with_for_update()
    return list((await uow.session.execute(query)).scalars().all())


def _group_lock_key(group_key: str) -> int:
    digest = hashlib.sha256(group_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def _lock_group(uow: UnitOfWork, group_key: str) -> None:
    """Lock an absent group as well as its existing rows on PostgreSQL."""

    bind = uow.session.get_bind()
    if bind.dialect.name == "postgresql":
        await uow.session.execute(select(func.pg_advisory_xact_lock(_group_lock_key(group_key))))


async def _emit_updated(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    spec: SettingGroupSpec,
    version: int,
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
                    "version": version,
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


def _field_value(spec: SettingGroupSpec, field_slug: str, value: Any) -> Any:
    field = spec.field(field_slug)
    adapter: TypeAdapter[Any] = TypeAdapter(spec.value_schema.model_fields[field.slug].annotation)
    return _json_normalize(adapter.validate_python(value))


class UpdateSettingGroup:
    """Merge, validate and atomically write a whole settings group."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, group_key: str, input_: UpdateSettingGroupInput) -> SettingGroupDTO:
        ctx = self._ctx
        spec = _require_group(ctx, group_key)
        _require_permission(ctx, spec.update_permission)
        async with ctx.uow_factory() as uow:
            await _lock_group(uow, group_key)
            rows = await _load_group_rows(uow, group_key, lock=True)
            _check_rows(spec, rows)
            current_version = _group_version(rows)
            if input_.expected_version != current_version:
                raise _conflict(
                    "settings.version_conflict",
                    f"expected version {input_.expected_version}, found {current_version}",
                )
            current = _effective_values(spec, rows)
            values = _validate_values(spec, _merged_update_values(spec, current, input_))
            next_version = current_version + 1
            existing = {row.field_slug: row for row in rows}
            for field in spec.fields:
                row = existing.get(field.slug)
                payload = SettingValuePayload(value=values[field.slug])
                if row is None:
                    uow.session.add(
                        SettingsValue(
                            group_key=group_key,
                            field_slug=field.slug,
                            schema_version=spec.version,
                            value=payload,
                            group_version=next_version,
                            updated_by=ctx.actor_id,
                        )
                    )
                else:
                    row.schema_version = spec.version
                    row.value = payload
                    row.group_version = next_version
                    row.updated_by = ctx.actor_id
            changed = tuple(
                field.slug
                for field in spec.fields
                if field.slug not in spec.sensitive_fields
                and values[field.slug] != current.get(field.slug)
            )
            await _emit_updated(
                ctx,
                uow,
                spec=spec,
                version=next_version,
                changed_fields=changed,
            )
            await _append_audit(
                ctx,
                uow,
                action="settings.update",
                group_key=group_key,
                details={"changed": list(changed)},
            )
            await uow.commit()
            updated_by = ctx.actor_id
            updated_at = ctx.clock.utc_now()
            return _to_dto(
                spec,
                values=values,
                version=next_version,
                updated_by=updated_by,
                updated_at=updated_at,
            )
        raise AssertionError("settings update transaction exited without returning")


class ResetSettingGroup:
    """Explicitly restore code defaults; audited and group-atomic."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, group_key: str) -> SettingGroupDTO:
        ctx = self._ctx
        spec = _require_group(ctx, group_key)
        _require_permission(ctx, spec.update_permission)
        async with ctx.uow_factory() as uow:
            await _lock_group(uow, group_key)
            rows = await _load_group_rows(uow, group_key, lock=True)
            _check_rows(spec, rows)
            current_version = _group_version(rows)
            current = _effective_values(spec, rows)
            defaults = spec.defaults()
            next_version = current_version + 1
            existing = {row.field_slug: row for row in rows}
            for field in spec.fields:
                row = existing.get(field.slug)
                payload = SettingValuePayload(value=defaults[field.slug])
                if row is None:
                    uow.session.add(
                        SettingsValue(
                            group_key=group_key,
                            field_slug=field.slug,
                            schema_version=spec.version,
                            value=payload,
                            group_version=next_version,
                            updated_by=ctx.actor_id,
                        )
                    )
                else:
                    row.schema_version = spec.version
                    row.value = payload
                    row.group_version = next_version
                    row.updated_by = ctx.actor_id
            changed = tuple(
                field.slug
                for field in spec.fields
                if field.slug not in spec.sensitive_fields
                and defaults[field.slug] != current.get(field.slug)
            )
            await _emit_updated(
                ctx,
                uow,
                spec=spec,
                version=next_version,
                changed_fields=changed,
            )
            await _append_audit(
                ctx,
                uow,
                action="settings.reset",
                group_key=group_key,
                details={"changed": list(changed)},
            )
            await uow.commit()
            return _to_dto(
                spec,
                values=defaults,
                version=next_version,
                updated_by=ctx.actor_id,
                updated_at=ctx.clock.utc_now(),
            )
        raise AssertionError("settings reset transaction exited without returning")


class SettingsQueries:
    """Read-only settings surface."""

    def __init__(self, *, uow_factory: UoWFactory, groups: SettingGroupRegistry) -> None:
        self._uow_factory = uow_factory
        self._groups = groups

    async def get_group(self, group_key: str) -> SettingGroupDTO:
        spec = _require_query_group(self._groups, group_key)
        async with self._uow_factory() as uow:
            rows = await _load_group_rows(uow, group_key)
        values = _effective_values(spec, rows)
        version = _group_version(rows)
        updated_by, updated_at = _updated_metadata(rows)
        return _to_dto(
            spec,
            values=values,
            version=version,
            updated_by=updated_by,
            updated_at=updated_at,
        )

    async def get_value(self, group_key: str, field_slug: str) -> Any:
        spec = _require_query_group(self._groups, group_key)
        field = spec.field(field_slug)
        async with self._uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(SettingsValue).where(
                            SettingsValue.group_key == group_key,
                            SettingsValue.field_slug == field.slug,
                        )
                    )
                )
                .scalars()
                .first()
            )
        if row is None:
            return spec.defaults()[field.slug]
        _check_rows(spec, [row])
        return _field_value(spec, field.slug, row.value.value)

    async def list_groups(self) -> list[SettingGroupDTO]:
        return [await self.get_group(spec.group_key) for spec in self._groups.specs()]

    async def get_public_settings(self) -> PublicSettingsDTO:
        """Only fields declared public per group; never sensitive values."""

        values: dict[str, dict[str, Any]] = {}
        for spec in self._groups.specs():
            group = await self.get_group(spec.group_key)
            values[spec.group_key] = {
                field.slug: group.values[field.slug]
                for field in spec.fields
                if field.public and not field.sensitive
            }
        return PublicSettingsDTO(values=values)
