"""Content commands.

Contract source: context/spec/capabilities/content.md §5/§8.

Every command runs in one UoW: business state, outbox events and audit
envelopes commit atomically in a single commit. Writes are conditional
updates (``WHERE version`` or ``WHERE status``) so concurrent callers
cannot lose updates or double-apply transitions; the command fails with a
conflict instead. Commands validate type, Pydantic data, transition,
permission, owner and optimistic version. Async scheduled publish is
idempotent through the workflow business key content_id:schedule_version.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from inc.capabilities.content.dto import to_dto
from inc.capabilities.content.events import _payload
from inc.capabilities.content.models import (
    PIN_RANK_MAX,
    Content,
    ContentDataEnvelope,
    ContentReference,
    ReferenceMetadata,
)
from inc.capabilities.content.schemas import (
    ContentDTO,
    CreateContentInput,
    ReplaceReferencesInput,
    SetContentPinInput,
    UpdateContentInput,
)
from inc.capabilities.content.types import ContentTypeRegistry, ContentTypeSpec
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"

PERMISSION_WRITE = "content.write"
PERMISSION_SCHEDULE = "content.schedule"
PERMISSION_PUBLISH = "content.publish"
PERMISSION_ARCHIVE = "content.archive"
PERMISSION_PIN = "content.pin"
PERMISSION_PURGE = "content.purge"
PERMISSION_MANAGE = "content.manage"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    types: ContentTypeRegistry
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None


def _forbidden(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.FORBIDDEN, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


def _validation(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


def _require_type(ctx: CommandContext, type_name: str) -> ContentTypeSpec:
    """Client-supplied type names are validation errors, not internal ones."""

    try:
        return ctx.types.require(type_name)
    except KernelError as exc:
        if exc.code == "content.unknown_type":
            raise _validation("content.unknown_type", exc.message) from exc
        raise


def _not_found(content_id: Any) -> KernelError:
    return KernelError(
        code="content.not_found", category=ErrorCategory.NOT_FOUND, message=f"content {content_id}"
    )


def _require_permission(ctx: CommandContext, key: str) -> None:
    if key not in ctx.permissions:
        raise _forbidden("content.forbidden", f"requires permission {key}")


def _require_owner(ctx: CommandContext, spec: ContentTypeSpec, row: Content) -> None:
    if spec.allows_owner and row.owner_id is not None:
        if ctx.actor_id != str(row.owner_id) and PERMISSION_MANAGE not in ctx.permissions:
            raise _forbidden("content.forbidden", "not the content owner")


def _validate_data(spec: ContentTypeSpec, data: dict[str, Any]) -> dict[str, Any]:
    return spec.data_schema.model_validate(data).model_dump(mode="json")


def _validate_slug(spec: ContentTypeSpec, slug: str) -> None:
    if not re.fullmatch(spec.slug_pattern, slug):
        raise _validation(
            "content.invalid_slug", f"slug {slug!r} does not match pattern {spec.slug_pattern}"
        )


def _validate_text(
    spec: ContentTypeSpec, title: str, body: str | None, excerpt: str | None
) -> None:
    if len(title) > spec.title_max_length:
        raise _validation("content.invalid_title", f"title longer than {spec.title_max_length}")
    if body is not None and spec.body_max_length is not None and len(body) > spec.body_max_length:
        raise _validation("content.invalid_body", f"body longer than {spec.body_max_length}")
    if (
        excerpt is not None
        and spec.excerpt_max_length is not None
        and len(excerpt) > spec.excerpt_max_length
    ):
        raise _validation(
            "content.invalid_excerpt", f"excerpt longer than {spec.excerpt_max_length}"
        )


async def _emit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    key: str,
    content_id: str,
    occurred_at: datetime,
    **values: Any,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=key,
            occurred_at=occurred_at,
            producer="content",
            aggregate_type="content",
            aggregate_id=content_id,
            trace_id=ctx.trace_id,
            payload=_payload(key, content_id=content_id, **values),
        ),
    )


async def _append_audit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    action: str,
    content: Content,
    occurred_at: datetime,
    details: dict[str, Any] | None = None,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=occurred_at,
            producer="content",
            aggregate_type="content",
            aggregate_id=str(content.id),
            trace_id=ctx.trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": occurred_at.isoformat(),
                "actor_type": "user" if ctx.actor_id else None,
                "actor_id": ctx.actor_id,
                "target_type": content.type_name,
                "target_id": str(content.id),
                "trace_id": ctx.trace_id,
                "details": details or {},
            },
        ),
    )


async def _get_row(uow: UnitOfWork, content_id: Any) -> Content:
    row: Content | None = await uow.session.get(Content, content_id)
    if row is None:
        raise _not_found(content_id)
    return row


async def _load_and_check(
    ctx: CommandContext,
    uow: UnitOfWork,
    content_id: Any,
    *,
    permission: str,
) -> tuple[Content, ContentTypeSpec]:
    row = await _get_row(uow, content_id)
    spec = ctx.types.require(row.type_name)
    _require_permission(ctx, permission)
    _require_owner(ctx, spec, row)
    return row, spec


async def _reload(uow: UnitOfWork, row: Content) -> Content:
    """Re-read the row after a Core-level conditional update."""

    await uow.session.refresh(row)
    return row


def _transition(ctx: CommandContext, row: Content, spec: ContentTypeSpec, target: str) -> None:
    if not spec.can_transition(row.status, target):
        raise _conflict(
            "content.invalid_transition",
            f"cannot move content from {row.status!r} to {target!r}",
        )


async def _transition_row(
    uow: UnitOfWork,
    row: Content,
    target: str,
    *,
    now: datetime,
    set_values: dict[str, Any],
) -> Content:
    """Atomic conditional transition; raises when the row moved concurrently."""

    result = await uow.session.execute(
        update(Content)
        .where(Content.id == row.id, Content.status == row.status)
        .values(status=target, version=Content.version + 1, updated_at=now, **set_values)
    )
    if result.rowcount == 0:
        raise _conflict(
            "content.invalid_transition",
            f"content moved concurrently from {row.status!r}; retry with fresh state",
        )
    return await _reload(uow, row)


async def _commit(uow: UnitOfWork, *, conflict_code: str | None = None) -> None:
    try:
        await uow.commit()
    except IntegrityError as exc:
        code = conflict_code or "content.state_conflict"
        raise _conflict(code, "content state changed or constraint violated") from exc


class CreateContent:
    """Create content in the type's default state."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: CreateContentInput) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_WRITE)
        spec = _require_type(ctx, input_.type_name)
        _validate_slug(spec, input_.slug)
        _validate_text(spec, input_.title, input_.body, input_.excerpt)
        payload = _validate_data(spec, input_.data)
        if input_.status is not None and input_.status != spec.default_state:
            raise _validation(
                "content.invalid_status", f"create must use default state {spec.default_state!r}"
            )
        if input_.owner_id is not None and not spec.allows_owner:
            raise _validation(
                "content.owner_not_allowed", f"type {spec.type_name} does not support owners"
            )
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row = Content(
                type_name=spec.type_name,
                schema_version=spec.data_schema_version,
                title=input_.title,
                slug=input_.slug,
                body=input_.body,
                excerpt=input_.excerpt,
                status=spec.default_state,
                owner_type="identity" if input_.owner_id is not None else None,
                owner_id=input_.owner_id,
                version=1,
                data=ContentDataEnvelope(schema_version=spec.data_schema_version, payload=payload),
            )
            uow.session.add(row)
            try:
                await uow.session.flush()  # assign id before events reference it
            except IntegrityError as exc:
                raise _conflict(
                    "content.duplicate_slug", f"slug {row.slug!r} already exists for this type"
                ) from exc
            await _emit(
                ctx,
                uow,
                key="content.created.v1",
                content_id=str(row.id),
                occurred_at=now,
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
                title=row.title,
            )
            await _append_audit(ctx, uow, action="content.create", content=row, occurred_at=now)
            await _commit(uow, conflict_code="content.duplicate_slug")
            return to_dto(row)


class UpdateContent:
    """Update editable fields with an atomic version-guarded write."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, input_: UpdateContentInput) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_WRITE)
            values: dict[str, Any] = {}
            if input_.title is not None:
                if len(input_.title) > spec.title_max_length:
                    raise _validation(
                        "content.invalid_title", f"title longer than {spec.title_max_length}"
                    )
                values["title"] = input_.title
            if input_.slug is not None:
                _validate_slug(spec, input_.slug)
                values["slug"] = input_.slug
            if input_.body is not None:
                if spec.body_max_length is not None and len(input_.body) > spec.body_max_length:
                    raise _validation(
                        "content.invalid_body", f"body longer than {spec.body_max_length}"
                    )
                values["body"] = input_.body
            if input_.excerpt is not None:
                if (
                    spec.excerpt_max_length is not None
                    and len(input_.excerpt) > spec.excerpt_max_length
                ):
                    raise _validation(
                        "content.invalid_excerpt",
                        f"excerpt longer than {spec.excerpt_max_length}",
                    )
                values["excerpt"] = input_.excerpt
            if input_.data is not None:
                values["data"] = ContentDataEnvelope(
                    schema_version=spec.data_schema_version,
                    payload=_validate_data(spec, input_.data),
                )
            if not values:
                raise _validation("content.empty_update", "nothing to update")
            result = await uow.session.execute(
                update(Content)
                .where(Content.id == row.id, Content.version == input_.expected_version)
                .values(**values, version=Content.version + 1, updated_at=now)
            )
            if result.rowcount == 0:
                raise _conflict(
                    "content.version_conflict",
                    f"expected version {input_.expected_version}, found {row.version}",
                )
            refreshed = await _reload(uow, row)
            await _emit(
                ctx,
                uow,
                key="content.updated.v1",
                content_id=str(refreshed.id),
                occurred_at=now,
                type_name=refreshed.type_name,
                slug=refreshed.slug,
                status=refreshed.status,
                version=refreshed.version,
                changed=tuple(sorted(values)),
            )
            await _append_audit(
                ctx,
                uow,
                action="content.update",
                content=refreshed,
                occurred_at=now,
                details={"changed": sorted(values)},
            )
            await _commit(uow, conflict_code="content.duplicate_slug")
            return to_dto(refreshed)


class SubmitContent:
    """draft -> pending (moderation pipeline start)."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_WRITE)
            _transition(ctx, row, spec, "pending")
            refreshed = await _transition_row(uow, row, "pending", now=now, set_values={})
            await _emit(
                ctx,
                uow,
                key="content.submitted.v1",
                content_id=str(refreshed.id),
                occurred_at=now,
                type_name=refreshed.type_name,
                slug=refreshed.slug,
                status=refreshed.status,
                version=refreshed.version,
            )
            await _append_audit(
                ctx, uow, action="content.submit", content=refreshed, occurred_at=now
            )
            await _commit(uow)
            return to_dto(refreshed)


class RejectContent:
    """pending -> rejected (moderation rejection)."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, reason: str | None = None) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_WRITE)
            _transition(ctx, row, spec, "rejected")
            refreshed = await _transition_row(uow, row, "rejected", now=now, set_values={})
            await _emit(
                ctx,
                uow,
                key="content.updated.v1",
                content_id=str(refreshed.id),
                occurred_at=now,
                type_name=refreshed.type_name,
                slug=refreshed.slug,
                status=refreshed.status,
                version=refreshed.version,
                changed=("status",),
            )
            await _append_audit(
                ctx,
                uow,
                action="content.reject",
                content=refreshed,
                occurred_at=now,
                details={"reason": reason} if reason else None,
            )
            await _commit(uow)
            return to_dto(refreshed)


class ScheduleContent:
    """status=scheduled with UTC publish_at; bumps schedule_version."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, publish_at: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        if publish_at.tzinfo is None:
            raise _validation("content.invalid_schedule", "publish_at must be tz-aware UTC")
        normalized = publish_at.astimezone(UTC)
        if normalized <= ctx.clock.utc_now():
            raise _validation("content.schedule_in_past", "publish_at must be in the future")
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_SCHEDULE)
            if not spec.allows_schedule:
                raise _validation(
                    "content.schedule_not_allowed",
                    f"type {spec.type_name} does not support scheduling",
                )
            _transition(ctx, row, spec, "scheduled")
            refreshed = await _transition_row(
                uow,
                row,
                "scheduled",
                now=now,
                set_values={
                    "publish_at": normalized,
                    "schedule_version": row.schedule_version + 1,
                },
            )
            await _emit(
                ctx,
                uow,
                key="content.scheduled.v1",
                content_id=str(refreshed.id),
                occurred_at=now,
                type_name=refreshed.type_name,
                slug=refreshed.slug,
                status=refreshed.status,
                version=refreshed.version,
                publish_at=refreshed.publish_at,
                schedule_version=refreshed.schedule_version,
            )
            await _append_audit(
                ctx, uow, action="content.schedule", content=refreshed, occurred_at=now
            )
            await _commit(uow)
            return to_dto(refreshed)


class UnscheduleContent:
    """scheduled -> draft; invalidates in-flight publish tasks."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_SCHEDULE)
            _transition(ctx, row, spec, "draft")
            refreshed = await _transition_row(
                uow,
                row,
                "draft",
                now=now,
                set_values={
                    "publish_at": None,
                    "schedule_version": row.schedule_version + 1,
                },
            )
            await _emit(
                ctx,
                uow,
                key="content.schedule_cancelled.v1",
                content_id=str(refreshed.id),
                occurred_at=now,
                type_name=refreshed.type_name,
                slug=refreshed.slug,
                status=refreshed.status,
                version=refreshed.version,
                schedule_version=refreshed.schedule_version,
            )
            await _append_audit(
                ctx, uow, action="content.unschedule", content=refreshed, occurred_at=now
            )
            await _commit(uow)
            return to_dto(refreshed)


class PublishContent:
    """Explicit publish from any allowed source state."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_PUBLISH)
            _transition(ctx, row, spec, "published")
            refreshed = await _transition_row(
                uow,
                row,
                "published",
                now=now,
                set_values={"published_at": now, "lease_owner": None, "lease_expires_at": None},
            )
            await _emit(
                ctx,
                uow,
                key="content.published.v1",
                content_id=str(refreshed.id),
                occurred_at=now,
                type_name=refreshed.type_name,
                slug=refreshed.slug,
                status=refreshed.status,
                version=refreshed.version,
                published_at=refreshed.published_at,
                schedule_version=refreshed.schedule_version,
            )
            await _append_audit(
                ctx, uow, action="content.publish", content=refreshed, occurred_at=now
            )
            await _commit(uow)
            return to_dto(refreshed)


class ArchiveContent:
    """published -> archived; clears the schedule reference."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_ARCHIVE)
            _transition(ctx, row, spec, "archived")
            refreshed = await _transition_row(
                uow,
                row,
                "archived",
                now=now,
                set_values={"archived_at": now, "publish_at": None},
            )
            await _emit(
                ctx,
                uow,
                key="content.archived.v1",
                content_id=str(refreshed.id),
                occurred_at=now,
                type_name=refreshed.type_name,
                slug=refreshed.slug,
                status=refreshed.status,
                version=refreshed.version,
            )
            await _append_audit(
                ctx, uow, action="content.archive", content=refreshed, occurred_at=now
            )
            await _commit(uow)
            return to_dto(refreshed)


class RestoreContentToDraft:
    """archived/rejected -> draft."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_WRITE)
            _transition(ctx, row, spec, "draft")
            refreshed = await _transition_row(
                uow,
                row,
                "draft",
                now=now,
                set_values={"archived_at": None, "publish_at": None},
            )
            await _emit(
                ctx,
                uow,
                key="content.updated.v1",
                content_id=str(refreshed.id),
                occurred_at=now,
                type_name=refreshed.type_name,
                slug=refreshed.slug,
                status=refreshed.status,
                version=refreshed.version,
                changed=("status",),
            )
            await _append_audit(
                ctx, uow, action="content.restore", content=refreshed, occurred_at=now
            )
            await _commit(uow)
            return to_dto(refreshed)


class SetContentPin:
    """Toggle pinning with bounded pin_rank."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, input_: SetContentPinInput) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        if not 0 <= input_.pin_rank <= PIN_RANK_MAX:
            raise _validation(
                "content.invalid_pin_rank", f"pin_rank must be within 0..{PIN_RANK_MAX}"
            )
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_PIN)
            if not spec.allows_pin:
                raise _validation(
                    "content.pin_not_allowed", f"type {spec.type_name} does not support pinning"
                )
            set_values: dict[str, Any] = {"is_pinned": input_.is_pinned}
            if input_.is_pinned:
                set_values["pin_rank"] = input_.pin_rank
            else:
                set_values["pin_rank"] = 0
            refreshed = await _transition_row(uow, row, row.status, now=now, set_values=set_values)
            await _emit(
                ctx,
                uow,
                key="content.pin_changed.v1",
                content_id=str(refreshed.id),
                occurred_at=now,
                type_name=refreshed.type_name,
                slug=refreshed.slug,
                status=refreshed.status,
                version=refreshed.version,
                is_pinned=refreshed.is_pinned,
                pin_rank=refreshed.pin_rank,
            )
            await _append_audit(ctx, uow, action="content.pin", content=refreshed, occurred_at=now)
            await _commit(uow)
            return to_dto(refreshed)


class ReplaceContentReferences:
    """Replace the outgoing references of one kind on a source content."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, input_: ReplaceReferencesInput) -> None:
        ctx = self._ctx
        metadata = ReferenceMetadata.model_validate(input_.metadata)
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_WRITE)
            if not spec.allows_references:
                raise _validation(
                    "content.references_not_allowed",
                    f"type {spec.type_name} does not support references",
                )
            seen: set[str] = set()
            for target_id in input_.targets:
                target: Content | None = await uow.session.get(Content, target_id)
                if target is None:
                    raise _validation(
                        "content.reference_target_missing",
                        f"reference target {target_id} does not exist",
                    )
                try:
                    target_spec = ctx.types.require(target.type_name)
                except KernelError as exc:
                    if exc.code == "content.unknown_type":
                        raise _validation("content.unknown_type", exc.message) from exc
                    raise
                if not target_spec.allows_incoming_references:
                    raise _validation(
                        "content.reference_target_not_allowed",
                        f"type {target.type_name} cannot be referenced",
                    )
                key = str(target_id)
                if key in seen:
                    raise _validation(
                        "content.reference_duplicate_target",
                        f"duplicate reference target {target_id}",
                    )
                seen.add(key)
            existing = (
                (
                    await uow.session.execute(
                        select(ContentReference).where(
                            ContentReference.source_content_id == row.id,
                            ContentReference.kind == input_.kind,
                        )
                    )
                )
                .scalars()
                .all()
            )
            # Serialize the replacement on the source row: bump version with a
            # conditional update so a concurrent replacement fails with a
            # conflict instead of silently losing one caller's references.
            cas = await uow.session.execute(
                update(Content)
                .where(Content.id == row.id, Content.version == row.version)
                .values(version=Content.version + 1, updated_at=now)
            )
            if cas.rowcount == 0:
                raise _conflict(
                    "content.version_conflict",
                    "content changed concurrently; retry with fresh state",
                )
            for ref in existing:
                await uow.session.delete(ref)
            await uow.session.flush()
            for position, target_id in enumerate(input_.targets):
                uow.session.add(
                    ContentReference(
                        source_content_id=row.id,
                        target_content_id=target_id,
                        kind=input_.kind,
                        position=position,
                        ref_metadata=metadata,
                    )
                )
            await _append_audit(
                ctx,
                uow,
                action="content.references",
                content=row,
                occurred_at=now,
                details={"kind": input_.kind, "targets": [str(t) for t in input_.targets]},
            )
            await _commit(uow)


class PurgeArchivedContent:
    """Operations command: physically purge an archived content.

    Dry-run reports what would be removed; a real purge refuses when
    incoming references exist and never cascades to referenced content.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, *, dry_run: bool = False) -> dict[str, Any]:  # type: ignore[return]
        ctx = self._ctx
        now = ctx.clock.utc_now()
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_PURGE)
            if row.status != "archived":
                raise _conflict(
                    "content.purge_requires_archived", "only archived content can be purged"
                )
            incoming = (
                (
                    await uow.session.execute(
                        select(ContentReference.id).where(
                            ContentReference.target_content_id == row.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if incoming:
                raise _conflict(
                    "content.incoming_references",
                    f"{len(incoming)} incoming references must be removed first",
                )
            outgoing = (
                (
                    await uow.session.execute(
                        select(ContentReference).where(ContentReference.source_content_id == row.id)
                    )
                )
                .scalars()
                .all()
            )
            report = {
                "content_id": str(row.id),
                "type_name": row.type_name,
                "outgoing_references": len(outgoing),
                "dry_run": dry_run,
            }
            if dry_run:
                await uow.commit()
                return report
            # Delete conditionally on status so a concurrent transition that
            # restored the content out of archived cannot have its change
            # silently lost by a plain id-based delete.
            purge = await uow.session.execute(
                delete(Content).where(Content.id == row.id, Content.status == "archived")
            )
            if purge.rowcount == 0:
                raise _conflict("content.purge_requires_archived", "content is no longer archived")
            for ref in outgoing:
                await uow.session.delete(ref)
            await _append_audit(
                ctx,
                uow,
                action="content.purge",
                content=row,
                occurred_at=now,
                details=report,
            )
            await _commit(uow)
            return report
