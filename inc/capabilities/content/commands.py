"""Content commands.

Contract source: context/spec/capabilities/content.md §5/§8.

Every command runs in one UoW: business state, outbox events and audit
envelopes commit atomically in a single commit. Commands validate type,
Pydantic data, transition, permission, owner and optimistic version.
Sync-command idempotency is provided by the natural keys ((type, slug)
uniqueness and the version counter); async scheduled publish is idempotent
through the workflow business key content_id:schedule_version.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
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
    **values: Any,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=key,
            occurred_at=ctx.clock.utc_now(),
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
    details: dict[str, Any] | None = None,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=ctx.clock.utc_now(),
            producer="content",
            aggregate_type="content",
            aggregate_id=str(content.id),
            trace_id=ctx.trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": ctx.clock.utc_now().isoformat(),
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


async def _finish(ctx: CommandContext, uow: UnitOfWork, *, conflict_code: str) -> None:
    try:
        await uow.commit()
    except IntegrityError as exc:
        raise _conflict(conflict_code, "slug already exists for this type") from exc


def _transition(ctx: CommandContext, row: Content, spec: ContentTypeSpec, target: str) -> None:
    if not spec.can_transition(row.status, target):
        raise _conflict(
            "content.invalid_transition",
            f"cannot move content from {row.status!r} to {target!r}",
        )


class CreateContent:
    """Create content in the type's default state."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: CreateContentInput) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_WRITE)
        spec = ctx.types.require(input_.type_name)
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
            await _emit(
                ctx,
                uow,
                key="content.created.v1",
                content_id=str(row.id),
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
                title=row.title,
            )
            await _append_audit(ctx, uow, action="content.create", content=row)
            await _finish(ctx, uow, conflict_code="content.duplicate_slug")
            return to_dto(row)


class UpdateContent:
    """Update editable fields with optimistic version check."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, input_: UpdateContentInput) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_WRITE)
            if row.version != input_.expected_version:
                raise _conflict(
                    "content.version_conflict",
                    f"expected version {input_.expected_version}, found {row.version}",
                )
            changed: list[str] = []
            if input_.title is not None:
                if len(input_.title) > spec.title_max_length:
                    raise _validation(
                        "content.invalid_title", f"title longer than {spec.title_max_length}"
                    )
                row.title = input_.title
                changed.append("title")
            if input_.slug is not None:
                _validate_slug(spec, input_.slug)
                row.slug = input_.slug
                changed.append("slug")
            if input_.body is not None:
                if spec.body_max_length is not None and len(input_.body) > spec.body_max_length:
                    raise _validation(
                        "content.invalid_body", f"body longer than {spec.body_max_length}"
                    )
                row.body = input_.body
                changed.append("body")
            if input_.excerpt is not None:
                if (
                    spec.excerpt_max_length is not None
                    and len(input_.excerpt) > spec.excerpt_max_length
                ):
                    raise _validation(
                        "content.invalid_excerpt",
                        f"excerpt longer than {spec.excerpt_max_length}",
                    )
                row.excerpt = input_.excerpt
                changed.append("excerpt")
            if input_.data is not None:
                row.data = ContentDataEnvelope(
                    schema_version=spec.data_schema_version,
                    payload=_validate_data(spec, input_.data),
                )
                changed.append("data")
            if not changed:
                raise _validation("content.empty_update", "nothing to update")
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="content.updated.v1",
                content_id=str(row.id),
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
                changed=tuple(changed),
            )
            await _append_audit(
                ctx, uow, action="content.update", content=row, details={"changed": changed}
            )
            await _finish(ctx, uow, conflict_code="content.duplicate_slug")
            return to_dto(row)


class SubmitContent:
    """draft -> pending (moderation pipeline start)."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_WRITE)
            _transition(ctx, row, spec, "pending")
            row.status = "pending"
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="content.submitted.v1",
                content_id=str(row.id),
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
            )
            await _append_audit(ctx, uow, action="content.submit", content=row)
            await uow.commit()
            return to_dto(row)


class RejectContent:
    """pending -> rejected (moderation rejection)."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, reason: str | None = None) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_WRITE)
            _transition(ctx, row, spec, "rejected")
            row.status = "rejected"
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="content.updated.v1",
                content_id=str(row.id),
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
                changed=("status",),
            )
            await _append_audit(
                ctx,
                uow,
                action="content.reject",
                content=row,
                details={"reason": reason} if reason else None,
            )
            await uow.commit()
            return to_dto(row)


class ScheduleContent:
    """status=scheduled with UTC publish_at; bumps schedule_version."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, publish_at: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        if publish_at.tzinfo is None:
            raise _validation("content.invalid_schedule", "publish_at must be tz-aware UTC")
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_SCHEDULE)
            if not spec.allows_schedule:
                raise _validation(
                    "content.schedule_not_allowed",
                    f"type {spec.type_name} does not support scheduling",
                )
            _transition(ctx, row, spec, "scheduled")
            if publish_at <= ctx.clock.utc_now():
                raise _validation("content.schedule_in_past", "publish_at must be in the future")
            row.status = "scheduled"
            row.publish_at = publish_at
            row.schedule_version += 1
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="content.scheduled.v1",
                content_id=str(row.id),
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
                publish_at=row.publish_at,
                schedule_version=row.schedule_version,
            )
            await _append_audit(ctx, uow, action="content.schedule", content=row)
            await uow.commit()
            return to_dto(row)


class UnscheduleContent:
    """scheduled -> draft; invalidates in-flight publish tasks."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_SCHEDULE)
            _transition(ctx, row, spec, "draft")
            row.status = "draft"
            row.publish_at = None
            row.schedule_version += 1
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="content.schedule_cancelled.v1",
                content_id=str(row.id),
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
                schedule_version=row.schedule_version,
            )
            await _append_audit(ctx, uow, action="content.unschedule", content=row)
            await uow.commit()
            return to_dto(row)


class PublishContent:
    """Explicit publish from any allowed source state."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_PUBLISH)
            _transition(ctx, row, spec, "published")
            now = ctx.clock.utc_now()
            row.status = "published"
            row.published_at = now
            row.lease_owner = None
            row.lease_expires_at = None
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="content.published.v1",
                content_id=str(row.id),
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
                published_at=row.published_at,
                schedule_version=row.schedule_version,
            )
            await _append_audit(ctx, uow, action="content.publish", content=row)
            await uow.commit()
            return to_dto(row)


class ArchiveContent:
    """published -> archived."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_ARCHIVE)
            _transition(ctx, row, spec, "archived")
            row.status = "archived"
            row.archived_at = ctx.clock.utc_now()
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="content.archived.v1",
                content_id=str(row.id),
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
            )
            await _append_audit(ctx, uow, action="content.archive", content=row)
            await uow.commit()
            return to_dto(row)


class RestoreContentToDraft:
    """archived/rejected -> draft."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any) -> ContentDTO:  # type: ignore[return]
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_WRITE)
            _transition(ctx, row, spec, "draft")
            row.status = "draft"
            row.archived_at = None
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="content.updated.v1",
                content_id=str(row.id),
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
                changed=("status",),
            )
            await _append_audit(ctx, uow, action="content.restore", content=row)
            await uow.commit()
            return to_dto(row)


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
        async with ctx.uow_factory() as uow:
            row, spec = await _load_and_check(ctx, uow, content_id, permission=PERMISSION_PIN)
            if not spec.allows_pin:
                raise _validation(
                    "content.pin_not_allowed", f"type {spec.type_name} does not support pinning"
                )
            row.is_pinned = input_.is_pinned
            row.pin_rank = input_.pin_rank if input_.is_pinned else 0
            row.version += 1
            await _emit(
                ctx,
                uow,
                key="content.pin_changed.v1",
                content_id=str(row.id),
                type_name=row.type_name,
                slug=row.slug,
                status=row.status,
                version=row.version,
                is_pinned=row.is_pinned,
                pin_rank=row.pin_rank,
            )
            await _append_audit(ctx, uow, action="content.pin", content=row)
            await uow.commit()
            return to_dto(row)


class ReplaceContentReferences:
    """Replace the outgoing references of one kind on a source content."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, input_: ReplaceReferencesInput) -> None:
        ctx = self._ctx
        metadata = ReferenceMetadata.model_validate(input_.metadata)
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
                target_spec = ctx.types.require(target.type_name)
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
                details={"kind": input_.kind, "targets": [str(t) for t in input_.targets]},
            )
            await uow.commit()


class PurgeArchivedContent:
    """Operations command: physically purge an archived content.

    Dry-run reports what would be removed; a real purge refuses when
    incoming references exist and never cascades to referenced content.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, content_id: Any, *, dry_run: bool = False) -> dict[str, Any]:  # type: ignore[return]
        ctx = self._ctx
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
            for ref in outgoing:
                await uow.session.delete(ref)
            await uow.session.delete(row)
            await _append_audit(ctx, uow, action="content.purge", content=row, details=report)
            await uow.commit()
            return report
