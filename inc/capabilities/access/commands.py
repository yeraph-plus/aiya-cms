"""Access commands.

Contract source: context/spec/capabilities/access.md §4.

Role and grant changes commit atomically with their events and audit
envelopes in one UoW. System roles are protected from deletion; capability
replacement is transactional (no partial sets under concurrency).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from inc.capabilities.access.models import AccessRole, AccessRoleCapability, AccessSubjectRole
from inc.capabilities.access.registry import PermissionRegistry
from inc.capabilities.access.schemas import RoleDTO, SubjectExists
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    permissions: PermissionRegistry
    subject_exists: SubjectExists
    audit_actor_id: str | None = None
    audit_trace_id: str | None = None


def _conflict(message: str) -> KernelError:
    return KernelError(code="access.conflict", category=ErrorCategory.CONFLICT, message=message)


def _not_found(message: str) -> KernelError:
    return KernelError(code="access.not_found", category=ErrorCategory.NOT_FOUND, message=message)


def _validation(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


def _to_role(role: AccessRole, capability_keys: list[str]) -> RoleDTO:
    return RoleDTO(
        id=str(role.id),
        name=role.name,
        slug=role.slug,
        description=role.description,
        system=role.system,
        capability_keys=capability_keys,
    )


async def _append_audit(
    uow: UnitOfWork,
    ctx: CommandContext,
    *,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=ctx.clock.utc_now(),
            producer="access",
            aggregate_type="access",
            aggregate_id=target_id,
            trace_id=ctx.audit_trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": ctx.clock.utc_now().isoformat(),
                "actor_type": "user" if ctx.audit_actor_id else None,
                "actor_id": ctx.audit_actor_id,
                "target_type": target_type,
                "target_id": target_id,
                "trace_id": ctx.audit_trace_id,
                "details": details or {},
            },
        ),
    )


async def _append_event(
    uow: UnitOfWork,
    ctx: CommandContext,
    *,
    event_key: str,
    payload: dict[str, Any],
    aggregate_id: str,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=event_key,
            occurred_at=ctx.clock.utc_now(),
            producer="access",
            aggregate_type="access",
            aggregate_id=aggregate_id,
            trace_id=ctx.audit_trace_id,
            payload=payload,
        ),
    )


class CreateRole:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, name: str, slug: str, description: str | None = None) -> RoleDTO:  # type: ignore[return]
        async with self._ctx.uow_factory() as uow:
            role = AccessRole(name=name, slug=slug, description=description, system=False)
            uow.session.add(role)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                await uow.rollback()
                raise _conflict("role slug already exists") from exc
            await _append_event(
                uow,
                self._ctx,
                event_key="access.role_changed.v1",
                payload={"role_id": str(role.id), "action": "created"},
                aggregate_id=str(role.id),
            )
            await _append_audit(
                uow,
                self._ctx,
                action="access.role.created",
                target_type="role",
                target_id=str(role.id),
                details={"slug": slug},
            )
            await uow.commit()
            return _to_role(role, [])


class UpdateRole:
    """Edit a role's display metadata while keeping its stable slug."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, role_id: str, name: str, description: str | None = None) -> RoleDTO:  # type: ignore[return]
        if not name.strip():
            raise _validation("role.name_required", "role name is required")
        async with self._ctx.uow_factory() as uow:
            role = await uow.session.get(AccessRole, uuid.UUID(role_id))
            if role is None:
                raise _not_found("role not found")
            if role.slug == "administrator":
                raise _conflict("administrator role is protected")
            role.name = name.strip()
            role.description = description.strip() if description else None
            keys = list(
                (
                    await uow.session.execute(
                        select(AccessRoleCapability.capability_key).where(
                            AccessRoleCapability.role_id == role.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            await _append_event(
                uow,
                self._ctx,
                event_key="access.role_changed.v1",
                payload={"role_id": role_id, "action": "updated"},
                aggregate_id=role_id,
            )
            await _append_audit(
                uow,
                self._ctx,
                action="access.role.updated",
                target_type="role",
                target_id=role_id,
            )
            await uow.commit()
            return _to_role(role, keys)


class DeleteRole:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, role_id: str) -> None:
        async with self._ctx.uow_factory() as uow:
            role = await uow.session.get(AccessRole, uuid.UUID(role_id))
            if role is None:
                raise _not_found("role not found")
            if role.system:
                raise _conflict("system roles cannot be deleted")
            await uow.session.delete(role)
            await _append_event(
                uow,
                self._ctx,
                event_key="access.role_changed.v1",
                payload={"role_id": role_id, "action": "deleted"},
                aggregate_id=role_id,
            )
            await _append_audit(
                uow,
                self._ctx,
                action="access.role.deleted",
                target_type="role",
                target_id=role_id,
            )
            await uow.commit()


class ReplaceRoleCapabilities:
    """Transactional, all-or-nothing capability replacement."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, role_id: str, capability_keys: list[str]) -> RoleDTO:  # type: ignore[return]
        for key in capability_keys:
            self._ctx.permissions.require(key)

        async with self._ctx.uow_factory() as uow:
            role = await uow.session.get(AccessRole, uuid.UUID(role_id))
            if role is None:
                raise _not_found("role not found")
            if role.slug == "administrator":
                raise _conflict("administrator role is protected")
            existing = (
                (
                    await uow.session.execute(
                        select(AccessRoleCapability).where(AccessRoleCapability.role_id == role.id)
                    )
                )
                .scalars()
                .all()
            )
            for row in existing:
                await uow.session.delete(row)
            for key in capability_keys:
                uow.session.add(AccessRoleCapability(role_id=role.id, capability_key=key))
            await _append_event(
                uow,
                self._ctx,
                event_key="access.role_changed.v1",
                payload={"role_id": role_id, "action": "capabilities_replaced"},
                aggregate_id=role_id,
            )
            await _append_audit(
                uow,
                self._ctx,
                action="access.role.capabilities_replaced",
                target_type="role",
                target_id=role_id,
                details={"keys": capability_keys},
            )
            await uow.commit()
            return _to_role(role, list(capability_keys))


class AssignRoleToSubject:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self,
        *,
        subject_type: str,
        subject_id: str,
        role_id: str,
        scope: str = "global",
    ) -> None:
        if scope not in ("global", "own"):
            raise KernelError(
                code="access.invalid_scope",
                category=ErrorCategory.VALIDATION,
                message=f"unknown scope {scope!r}",
            )
        if not await self._ctx.subject_exists.exists(subject_type, subject_id):
            raise KernelError(
                code="access.subject_not_found",
                category=ErrorCategory.VALIDATION,
                message=f"subject {subject_type}:{subject_id} does not exist",
            )
        async with self._ctx.uow_factory() as uow:
            role = await uow.session.get(AccessRole, uuid.UUID(role_id))
            if role is None:
                raise _not_found("role not found")
            uow.session.add(
                AccessSubjectRole(
                    subject_type=subject_type,
                    subject_id=subject_id,
                    role_id=role.id,
                    scope=scope,
                )
            )
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                await uow.rollback()
                raise _conflict("role already assigned to subject") from exc
            await _append_event(
                uow,
                self._ctx,
                event_key="access.subject_role_assigned.v1",
                payload={
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "role_id": role_id,
                    "scope": scope,
                },
                aggregate_id=subject_id,
            )
            await _append_audit(
                uow,
                self._ctx,
                action="access.subject.role_assigned",
                target_type="subject",
                target_id=subject_id,
                details={"role_id": role_id, "scope": scope},
            )
            await uow.commit()


class RevokeRoleFromSubject:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, subject_type: str, subject_id: str, role_id: str) -> None:
        async with self._ctx.uow_factory() as uow:
            grant = (
                (
                    await uow.session.execute(
                        select(AccessSubjectRole).where(
                            AccessSubjectRole.subject_type == subject_type,
                            AccessSubjectRole.subject_id == subject_id,
                            AccessSubjectRole.role_id == uuid.UUID(role_id),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if grant is None:
                raise _not_found("role grant not found")
            await uow.session.delete(grant)
            await _append_event(
                uow,
                self._ctx,
                event_key="access.subject_role_revoked.v1",
                payload={
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "role_id": role_id,
                },
                aggregate_id=subject_id,
            )
            await _append_audit(
                uow,
                self._ctx,
                action="access.subject.role_revoked",
                target_type="subject",
                target_id=subject_id,
                details={"role_id": role_id},
            )
            await uow.commit()


class BootstrapAdministrator:
    """Ops-only bootstrap that enforces a single system administrator.

    ``install`` is the only caller. A target subject that already holds the
    administrator role is idempotent; binding a second, different subject is
    refused so the system can never end up with more than one super admin.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, subject_type: str, subject_id: str) -> RoleDTO:  # type: ignore[return]
        if not await self._ctx.subject_exists.exists(subject_type, subject_id):
            raise KernelError(
                code="access.subject_not_found",
                category=ErrorCategory.VALIDATION,
                message=f"subject {subject_type}:{subject_id} does not exist",
            )
        async with self._ctx.uow_factory() as uow:
            role = (
                (
                    await uow.session.execute(
                        select(AccessRole)
                        .where(AccessRole.slug == "administrator")
                        .with_for_update()
                    )
                )
                .scalars()
                .first()
            )
            created = role is None
            if role is None:
                role = AccessRole(
                    name="Administrator",
                    slug="administrator",
                    description="System administrator role",
                    system=True,
                )
                uow.session.add(role)
                try:
                    await uow.session.flush()
                except IntegrityError:
                    # A concurrent bootstrap created the administrator role
                    # first; reload it under the row lock and continue.
                    await uow.rollback()
                    role = (
                        (
                            await uow.session.execute(
                                select(AccessRole)
                                .where(AccessRole.slug == "administrator")
                                .with_for_update()
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if role is None:
                        raise
                    created = False

            existing_grant = (
                (
                    await uow.session.execute(
                        select(AccessSubjectRole).where(AccessSubjectRole.role_id == role.id)
                    )
                )
                .scalars()
                .all()
            )
            target_holds = [
                grant
                for grant in existing_grant
                if grant.subject_type == subject_type and grant.subject_id == subject_id
            ]
            other_holds = [
                grant
                for grant in existing_grant
                if not (grant.subject_type == subject_type and grant.subject_id == subject_id)
            ]
            if other_holds:
                raise KernelError(
                    code="access.administrator_exists",
                    category=ErrorCategory.CONFLICT,
                    message=("an administrator already exists; only one super admin is allowed"),
                )
            existing_keys = {
                row.capability_key
                for row in (
                    (
                        await uow.session.execute(
                            select(AccessRoleCapability).where(
                                AccessRoleCapability.role_id == role.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            }
            # The administrator role is a protected projection of the
            # currently registered permission registry.  Re-running install
            # must repair permissions added after the original bootstrap,
            # even when the subject binding itself is already present.
            for key in self._ctx.permissions.keys():
                if key not in existing_keys:
                    uow.session.add(AccessRoleCapability(role_id=role.id, capability_key=key))

            if target_holds:
                await uow.commit()
                return _to_role(role, list(self._ctx.permissions.keys()))

            uow.session.add(
                AccessSubjectRole(
                    subject_type=subject_type,
                    subject_id=subject_id,
                    role_id=role.id,
                    scope="global",
                )
            )

            # Reach this point only when a new grant is actually created
            # (the idempotent target_holds path returns earlier). Audit the
            # security-sensitive grant regardless of whether the role was
            # created or already existed.
            await _append_audit(
                uow,
                self._ctx,
                action="access.bootstrap.administrator",
                target_type="role",
                target_id=str(role.id),
                details={
                    "subject": f"{subject_type}:{subject_id}",
                    "role_created": created,
                },
            )
            await uow.commit()
            return _to_role(role, list(self._ctx.permissions.keys()))


BASE_ROLE_TEMPLATES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "Editor",
        "editor",
        "Content editor",
        (
            "admin.dashboard.read",
            "content.read",
            "content.write",
            "content.schedule",
            "content.publish",
            "content.archive",
            "content.pin",
            "content.manage",
            "taxonomy.read",
            "taxonomy.manage",
            "assets.read",
            "assets.upload",
            "comments.read",
            "comments.moderate",
            "comments.delete",
            "community.read_admin",
            "community.posts.moderate",
            "community.tags.manage",
            "community.discussions.lock",
            "community.discussions.archive",
        ),
    ),
    (
        "Author",
        "author",
        "Content author",
        (
            "content.read",
            "content.write",
            "taxonomy.read",
            "assets.read",
            "assets.upload",
        ),
    ),
    (
        "User",
        "user",
        "Registered user",
        (
            "community.discussions.create",
            "community.discussions.reply",
            "community.discussions.edit_own",
            "comments.submit",
        ),
    ),
)


class EnsureBaseRoles:
    """Create/update the protected Editor/Author/User role templates."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self) -> dict[str, str]:
        result: dict[str, str] = {}
        async with self._ctx.uow_factory() as uow:
            for name, slug, description, keys in BASE_ROLE_TEMPLATES:
                role = (
                    (
                        await uow.session.execute(
                            select(AccessRole).where(AccessRole.slug == slug).with_for_update()
                        )
                    )
                    .scalars()
                    .first()
                )
                if role is None:
                    role = AccessRole(name=name, slug=slug, description=description, system=True)
                    uow.session.add(role)
                    await uow.session.flush()
                elif not role.system:
                    role.system = True
                role.name = name
                role.description = description
                existing = {
                    row.capability_key
                    for row in (
                        await uow.session.execute(
                            select(AccessRoleCapability).where(
                                AccessRoleCapability.role_id == role.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                }
                stale = existing.difference(keys)
                if stale:
                    await uow.session.execute(
                        delete(AccessRoleCapability).where(
                            AccessRoleCapability.role_id == role.id,
                            AccessRoleCapability.capability_key.in_(stale),
                        )
                    )
                for key in keys:
                    self._ctx.permissions.require(key)
                    if key not in existing:
                        uow.session.add(AccessRoleCapability(role_id=role.id, capability_key=key))
                result[slug] = str(role.id)
            await uow.commit()
        return result


class AssignDefaultUserRole:
    """Idempotently attach the protected User role to a new identity."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, subject_type: str, subject_id: str) -> None:
        if not await self._ctx.subject_exists.exists(subject_type, subject_id):
            raise KernelError(
                code="access.subject_not_found",
                category=ErrorCategory.VALIDATION,
                message=f"subject {subject_type}:{subject_id} does not exist",
            )
        async with self._ctx.uow_factory() as uow:
            await self.assign_in_uow(
                uow,
                subject_type=subject_type,
                subject_id=subject_id,
            )
            await uow.commit()

    async def assign_in_uow(
        self,
        uow: UnitOfWork,
        *,
        subject_type: str,
        subject_id: str,
    ) -> None:
        """Attach the role without committing a caller-owned transaction.

        This method is reserved for composition workflows that have already
        created and validated the opaque subject in the same UoW.
        """

        role = (
            (await uow.session.execute(select(AccessRole).where(AccessRole.slug == "user")))
            .scalars()
            .first()
        )
        if role is None:
            raise _not_found("base user role not initialized")
        existing = (
            (
                await uow.session.execute(
                    select(AccessSubjectRole).where(
                        AccessSubjectRole.subject_type == subject_type,
                        AccessSubjectRole.subject_id == subject_id,
                        AccessSubjectRole.role_id == role.id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            uow.session.add(
                AccessSubjectRole(
                    subject_type=subject_type,
                    subject_id=subject_id,
                    role_id=role.id,
                    scope="global",
                )
            )
