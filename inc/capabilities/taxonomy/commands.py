"""Taxonomy commands.

Contract source: context/spec/capabilities/taxonomy.md §4.

Term CRUD validates dimension, term schema, status and permissions;
AssignTerms replaces a target's term set per dimension and validates
selection counts, target type and existence through the consumer Port.
Unknown dimensions are never auto-created.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from inc.capabilities.taxonomy.dimensions import DimensionRegistry, DimensionSpec
from inc.capabilities.taxonomy.events import TAXONOMY_EVENT_SCHEMAS
from inc.capabilities.taxonomy.models import (
    TaxonomyAssignment,
    TaxonomyDimension,
    TaxonomyTerm,
    TermData,
)
from inc.capabilities.taxonomy.ports import TargetExistsPort
from inc.capabilities.taxonomy.schemas import (
    AssignTermsInput,
    CreateTermInput,
    TermDTO,
    UpdateTermInput,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"

PERMISSION_MANAGE = "taxonomy.manage"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    dimensions: DimensionRegistry
    target_exists: TargetExistsPort
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
        raise _forbidden("taxonomy.forbidden", f"requires permission {key}")


def _require_dimension(ctx: CommandContext, dimension_key: str) -> DimensionSpec:
    """Client-supplied dimensions are validation errors, not internal ones."""

    try:
        return ctx.dimensions.require(dimension_key)
    except KernelError as exc:
        if exc.code == "taxonomy.unknown_dimension":
            raise KernelError(
                code="taxonomy.unknown_dimension",
                category=ErrorCategory.VALIDATION,
                message=exc.message,
            ) from exc
        raise


def _require_manage_permission(ctx: CommandContext, spec: DimensionSpec) -> None:
    if spec.manage_permission is not None:
        _require_permission(ctx, spec.manage_permission)
    else:
        _require_permission(ctx, PERMISSION_MANAGE)


def _validate_slug(spec: DimensionSpec, slug: str) -> None:
    if not re.fullmatch(spec.term_slug_pattern, slug):
        raise _validation(
            "taxonomy.invalid_slug",
            f"slug {slug!r} does not match pattern {spec.term_slug_pattern}",
        )


def _validate_term_schema(spec: DimensionSpec, metadata: dict[str, Any]) -> dict[str, Any]:
    return spec.term_schema.model_validate(metadata).model_dump(mode="json")


async def _emit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    key: str,
    **values: Any,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=key,
            occurred_at=ctx.clock.utc_now(),
            producer="taxonomy",
            aggregate_type="taxonomy",
            aggregate_id=values.get("dimension_key", "taxonomy"),
            trace_id=ctx.trace_id,
            payload=TAXONOMY_EVENT_SCHEMAS[key].model_validate(values).model_dump(mode="json"),
        ),
    )


async def _append_audit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    action: str,
    dimension_key: str,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=ctx.clock.utc_now(),
            producer="taxonomy",
            aggregate_type="taxonomy",
            aggregate_id=dimension_key,
            trace_id=ctx.trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": ctx.clock.utc_now().isoformat(),
                "actor_type": "user" if ctx.actor_id else None,
                "actor_id": ctx.actor_id,
                "target_type": target_type or "dimension",
                "target_id": target_id or dimension_key,
                "trace_id": ctx.trace_id,
                "details": details or {},
            },
        ),
    )


def _to_dto(row: TaxonomyTerm) -> TermDTO:
    return TermDTO(
        id=str(row.id),
        dimension_key=row.dimension_key,
        name=row.name,
        slug=row.slug,
        description=row.description,
        metadata=dict(row.term_metadata.values),
        status=row.status,
    )


class CreateTerm:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, dimension_key: str, input_: CreateTermInput) -> TermDTO:  # type: ignore[return]
        ctx = self._ctx
        spec = _require_dimension(ctx, dimension_key)
        _require_manage_permission(ctx, spec)
        _validate_slug(spec, input_.slug)
        payload = _validate_term_schema(spec, input_.metadata)
        async with ctx.uow_factory() as uow:
            row = TaxonomyTerm(
                dimension_key=dimension_key,
                name=input_.name,
                slug=input_.slug,
                description=input_.description,
                term_metadata=TermData(values=payload),
            )
            uow.session.add(row)
            try:
                await uow.session.flush()  # assign id before events reference it
            except IntegrityError as exc:
                raise _conflict(
                    "taxonomy.duplicate_slug",
                    f"slug {input_.slug!r} already exists for dimension {dimension_key}",
                ) from exc
            await _emit(
                ctx,
                uow,
                key="taxonomy.term_created.v1",
                dimension_key=dimension_key,
                term_id=str(row.id),
                slug=row.slug,
                name=row.name,
            )
            await _append_audit(
                ctx, uow, action="taxonomy.create_term", dimension_key=dimension_key
            )
            await uow.commit()
            return _to_dto(row)


class UpdateTerm:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, term_id: Any, input_: UpdateTermInput) -> TermDTO:  # type: ignore[return]
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            row: TaxonomyTerm | None = await uow.session.get(TaxonomyTerm, term_id)
            if row is None:
                raise KernelError(
                    code="taxonomy.term_not_found",
                    category=ErrorCategory.NOT_FOUND,
                    message=f"term {term_id}",
                )
            spec = ctx.dimensions.require(row.dimension_key)
            _require_manage_permission(ctx, spec)
            changed = False
            if input_.name is not None:
                if input_.name != row.name:
                    row.name = input_.name
                    changed = True
            if input_.description is not None:
                if input_.description != row.description:
                    row.description = input_.description
                    changed = True
            if input_.metadata is not None:
                payload = _validate_term_schema(spec, input_.metadata)
                if payload != row.term_metadata.values:
                    row.term_metadata = TermData(values=payload)
                    changed = True
            if not changed:
                raise KernelError(
                    code="taxonomy.empty_update",
                    category=ErrorCategory.VALIDATION,
                    message="nothing to update",
                )
            await _emit(
                ctx,
                uow,
                key="taxonomy.term_updated.v1",
                dimension_key=row.dimension_key,
                term_id=str(row.id),
                slug=row.slug,
            )
            await _append_audit(
                ctx, uow, action="taxonomy.update_term", dimension_key=row.dimension_key
            )
            await uow.commit()
            return _to_dto(row)


class ArchiveTerm:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, term_id: Any) -> TermDTO:  # type: ignore[return]
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            row: TaxonomyTerm | None = await uow.session.get(TaxonomyTerm, term_id)
            if row is None:
                raise KernelError(
                    code="taxonomy.term_not_found",
                    category=ErrorCategory.NOT_FOUND,
                    message=f"term {term_id}",
                )
            spec = ctx.dimensions.require(row.dimension_key)
            _require_manage_permission(ctx, spec)
            if row.status != "archived":
                row.status = "archived"
                row.archived_at = ctx.clock.utc_now()
            else:
                return _to_dto(row)
            await _emit(
                ctx,
                uow,
                key="taxonomy.term_archived.v1",
                dimension_key=row.dimension_key,
                term_id=str(row.id),
                slug=row.slug,
            )
            await _append_audit(
                ctx, uow, action="taxonomy.archive_term", dimension_key=row.dimension_key
            )
            await uow.commit()
            return _to_dto(row)


class AssignTerms:
    """Replace a target's term set for one dimension (OR within, AND across)."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, dimension_key: str, input_: AssignTermsInput) -> None:
        ctx = self._ctx
        spec = _require_dimension(ctx, dimension_key)
        _require_manage_permission(ctx, spec)
        if not spec.accepts_target(input_.target_type):
            raise _validation(
                "taxonomy.target_type_not_allowed",
                f"dimension {dimension_key} does not accept target type {input_.target_type!r}",
            )
        if len(input_.term_ids) < spec.min_items:
            raise _validation(
                "taxonomy.too_few_terms",
                f"dimension {dimension_key} requires at least {spec.min_items} terms",
            )
        if len(input_.term_ids) > spec.max_items:
            raise _validation(
                "taxonomy.too_many_terms",
                f"dimension {dimension_key} allows at most {spec.max_items} terms",
            )
        if len(set(input_.term_ids)) != len(input_.term_ids):
            raise _validation("taxonomy.duplicate_term", "duplicate term ids in assignment")
        if not await ctx.target_exists(input_.target_type, str(input_.target_id)):
            raise _validation(
                "taxonomy.target_missing", f"target {input_.target_type}:{input_.target_id}"
            )
        async with ctx.uow_factory() as uow:
            term_rows = (
                (
                    await uow.session.execute(
                        select(TaxonomyTerm).where(
                            TaxonomyTerm.id.in_(input_.term_ids),
                            TaxonomyTerm.dimension_key == dimension_key,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(term_rows) != len(input_.term_ids):
                raise _validation(
                    "taxonomy.unknown_term", "one or more terms are unknown for this dimension"
                )
            inactive = [t.slug for t in term_rows if t.status != "active"]
            if inactive:
                raise _validation(
                    "taxonomy.term_inactive", f"terms are not active: {', '.join(inactive)}"
                )
            existing = (
                (
                    await uow.session.execute(
                        select(TaxonomyAssignment).where(
                            TaxonomyAssignment.dimension_key == dimension_key,
                            TaxonomyAssignment.target_type == input_.target_type,
                            TaxonomyAssignment.target_id == input_.target_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in existing:
                await uow.session.delete(row)
            await uow.session.flush()
            for position, term_id in enumerate(input_.term_ids):
                uow.session.add(
                    TaxonomyAssignment(
                        dimension_key=dimension_key,
                        term_id=term_id,
                        target_type=input_.target_type,
                        target_id=input_.target_id,
                        position=position,
                    )
                )
            await _emit(
                ctx,
                uow,
                key="taxonomy.assignments_replaced.v1",
                dimension_key=dimension_key,
                target_type=input_.target_type,
                target_id=str(input_.target_id),
                term_ids=tuple(str(t) for t in input_.term_ids),
            )
            await _append_audit(
                ctx,
                uow,
                action="taxonomy.assign",
                dimension_key=dimension_key,
                target_type=input_.target_type,
                target_id=str(input_.target_id),
                details={"term_ids": [str(t) for t in input_.term_ids]},
            )
            await uow.commit()


class RemoveTargetAssignments:
    """Called by target-deletion workflows; idempotent."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, target_type: str, target_id: str) -> None:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_MANAGE)
        try:
            parsed = uuid.UUID(target_id)
        except ValueError as exc:
            raise KernelError(
                code="taxonomy.invalid_uuid",
                category=ErrorCategory.VALIDATION,
                message=f"invalid target_id {target_id!r}",
            ) from exc
        async with ctx.uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(TaxonomyAssignment).where(
                            TaxonomyAssignment.target_type == target_type,
                            TaxonomyAssignment.target_id == parsed,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                await uow.session.delete(row)
            await uow.commit()


class SyncDimensionDefinitions:
    """Ops command: mirror code declarations into taxonomy_dimensions.

    Dry-run reports what would change without writing; a real sync updates
    only the non-executing mirror rows.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, dry_run: bool = True) -> dict[str, Any]:  # type: ignore[return]
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_MANAGE)
        changes: dict[str, str] = {}
        async with ctx.uow_factory() as uow:
            existing = {
                row.dimension_key: row
                for row in (await uow.session.execute(select(TaxonomyDimension))).scalars()
            }
            for spec in ctx.dimensions.specs():
                row = existing.get(spec.dimension_key)
                if row is None:
                    changes[spec.dimension_key] = "create"
                    if not dry_run:
                        uow.session.add(
                            TaxonomyDimension(
                                dimension_key=spec.dimension_key,
                                spec_version=spec.version,
                                selection_mode=spec.selection_mode,
                            )
                        )
                elif row.spec_version != spec.version or row.selection_mode != spec.selection_mode:
                    changes[spec.dimension_key] = "update"
                    if not dry_run:
                        row.spec_version = spec.version
                        row.selection_mode = spec.selection_mode
            if not dry_run:
                await uow.commit()
            return {"dry_run": dry_run, "changes": changes}
