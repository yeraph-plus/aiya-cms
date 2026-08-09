"""Access capability tests.

Contract source: context/spec/capabilities/access.md §9.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.access.authorize import AuthorizeService
from inc.capabilities.access.commands import (
    AssignRoleToSubject,
    BootstrapAdministrator,
    CommandContext,
    CreateRole,
    DeleteRole,
    ReplaceRoleCapabilities,
    RevokeRoleFromSubject,
)
from inc.capabilities.access.events import ACCESS_EVENT_SCHEMAS
from inc.capabilities.access.models import AccessRoleCapability, AccessSubjectRole
from inc.capabilities.access.queries import AccessDiagnostics
from inc.capabilities.access.registry import PermissionRegistry
from inc.capabilities.access.schemas import Principal
from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxWriter


class FakeSubjectExists:
    def __init__(self, known: set[str]) -> None:
        self._known = known

    async def exists(self, subject_type: str, subject_id: str) -> bool:
        return subject_type == "identity" and subject_id in self._known


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in ACCESS_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def permissions() -> PermissionRegistry:
    registry = PermissionRegistry()
    registry.register_declared("identity", ("identity.users.read", "identity.users.ban"))
    registry.register_declared("content", ("content.publish", "content.archive"))
    registry.register_declared("points", ("points.adjust",))
    return registry


@pytest.fixture
def access_ctx(
    uow_factory: UoWFactory,
    clock: Any,
    schema_registry: EventSchemaRegistry,
    permissions: PermissionRegistry,
) -> CommandContext:
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        permissions=permissions,
        subject_exists=FakeSubjectExists(known={"u-1", "u-2"}),
        audit_actor_id="test-admin",
    )


def test_permission_registry_validation(permissions: PermissionRegistry) -> None:
    with pytest.raises(KernelError):
        permissions.register("identity.users.read", owner="identity")  # duplicate
    with pytest.raises(KernelError):
        permissions.register("content.publish", owner="identity")  # owner mismatch
    with pytest.raises(ValueError):
        permissions.register("no-dots", owner="identity")
    assert permissions.contains("content.publish")
    permissions.freeze()
    with pytest.raises(KernelError):
        permissions.register("content.new.v1", owner="content")


def test_permission_key_rejects_trailing_newline(permissions: PermissionRegistry) -> None:
    """Trailing newline must not slip past the dotted-key regex (`$`-anchored
    `.match()` accepted `foo.bar\n`); use fullmatch so control chars fail."""
    with pytest.raises(ValueError):
        permissions.register("content.publish\n", owner="content")


async def test_role_lifecycle_and_protected_system_role(
    access_ctx: CommandContext,
) -> None:
    role = await CreateRole(access_ctx)(name="Editor", slug="editor")
    await ReplaceRoleCapabilities(access_ctx)(
        role_id=role.id, capability_keys=["content.publish", "content.archive"]
    )
    await DeleteRole(access_ctx)(role_id=role.id)
    with pytest.raises(KernelError) as excinfo:
        await ReplaceRoleCapabilities(access_ctx)(
            role_id=role.id, capability_keys=["content.publish"]
        )
    assert excinfo.value.code == "access.not_found"


async def test_unregistered_permission_cannot_be_bound(
    access_ctx: CommandContext,
) -> None:
    role = await CreateRole(access_ctx)(name="Ghost", slug="ghost")
    with pytest.raises(KernelError) as excinfo:
        await ReplaceRoleCapabilities(access_ctx)(
            role_id=role.id, capability_keys=["ghost.key.not_registered"]
        )
    assert excinfo.value.code == "kernel.registry_unknown"


async def test_default_deny_and_own_scope(
    access_ctx: CommandContext,
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    role = await CreateRole(access_ctx)(name="Publisher", slug="publisher")
    await ReplaceRoleCapabilities(access_ctx)(role_id=role.id, capability_keys=["content.publish"])
    await AssignRoleToSubject(access_ctx)(
        subject_type="identity", subject_id="u-1", role_id=role.id, scope="global"
    )
    authorizer = AuthorizeService(uow_factory=uow_factory, clock=clock)
    principal = Principal(subject_id="u-1", status="active")

    decision = await authorizer.decide(principal, "content.publish")
    assert decision.allowed
    denied = await authorizer.decide(principal, "points.adjust")
    assert not denied.allowed
    assert denied.reason == "deny.no_grant"

    # Banned and anonymous principals are denied.
    banned = Principal(subject_id="u-1", status="banned")
    assert not (await authorizer.decide(banned, "content.publish")).allowed
    anonymous = Principal(subject_id="", status="anonymous")
    assert not (await authorizer.decide(anonymous, "content.publish")).allowed


async def test_own_scoped_grant_does_not_satisfy_global_scope(
    access_ctx: CommandContext,
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    role = await CreateRole(access_ctx)(name="SelfPublisher", slug="self_publisher")
    await ReplaceRoleCapabilities(access_ctx)(role_id=role.id, capability_keys=["content.publish"])
    await AssignRoleToSubject(access_ctx)(
        subject_type="identity",
        subject_id="u-1",
        role_id=role.id,
        scope="own",
    )
    authorizer = AuthorizeService(uow_factory=uow_factory, clock=clock)
    principal = Principal(subject_id="u-1", status="active")

    # A grant scoped "own" must not satisfy a global-scope request.
    global_decision = await authorizer.decide(principal, "content.publish", scope="global")
    assert not global_decision.allowed
    assert global_decision.reason == "deny.scope"

    # The same grant does satisfy an own-scope request.
    own_decision = await authorizer.decide(principal, "content.publish", scope="own")
    assert own_decision.allowed
    assert own_decision.reason == "allow.own"


async def test_global_scoped_grant_satisfies_own_scope(
    access_ctx: CommandContext,
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    role = await CreateRole(access_ctx)(name="GlobalPublisher", slug="global_publisher")
    await ReplaceRoleCapabilities(access_ctx)(role_id=role.id, capability_keys=["content.publish"])
    await AssignRoleToSubject(access_ctx)(
        subject_type="identity",
        subject_id="u-1",
        role_id=role.id,
        scope="global",
    )
    authorizer = AuthorizeService(uow_factory=uow_factory, clock=clock)
    principal = Principal(subject_id="u-1", status="active")

    assert (await authorizer.decide(principal, "content.publish", scope="global")).allowed
    assert (await authorizer.decide(principal, "content.publish", scope="own")).allowed


async def test_revocation_takes_effect_immediately(
    access_ctx: CommandContext,
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    role = await CreateRole(access_ctx)(name="Publisher", slug="publisher")
    await ReplaceRoleCapabilities(access_ctx)(role_id=role.id, capability_keys=["content.publish"])
    await AssignRoleToSubject(access_ctx)(
        subject_type="identity", subject_id="u-1", role_id=role.id
    )
    authorizer = AuthorizeService(uow_factory=uow_factory, clock=clock)
    principal = Principal(subject_id="u-1", status="active")
    assert (await authorizer.decide(principal, "content.publish")).allowed

    await RevokeRoleFromSubject(access_ctx)(
        subject_type="identity", subject_id="u-1", role_id=role.id
    )
    assert not (await authorizer.decide(principal, "content.publish")).allowed


async def test_assign_rejects_unknown_subject(access_ctx: CommandContext) -> None:
    role = await CreateRole(access_ctx)(name="Publisher", slug="publisher")
    with pytest.raises(KernelError) as excinfo:
        await AssignRoleToSubject(access_ctx)(
            subject_type="identity", subject_id="ghost", role_id=role.id
        )
    assert excinfo.value.code == "access.subject_not_found"


async def test_bootstrap_administrator_is_idempotent(
    access_ctx: CommandContext,
    permissions: PermissionRegistry,
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    first = await BootstrapAdministrator(access_ctx)(subject_type="identity", subject_id="u-1")
    assert first.system
    assert set(first.capability_keys) == set(permissions.keys())
    second = await BootstrapAdministrator(access_ctx)(subject_type="identity", subject_id="u-1")
    assert second.id == first.id

    async with uow_factory() as uow:
        grants = (await uow.session.execute(select(AccessSubjectRole))).scalars().all()
        caps = (await uow.session.execute(select(AccessRoleCapability))).scalars().all()
    assert len(grants) == 1
    assert len(caps) == len(permissions.keys())

    # System role cannot be deleted.
    with pytest.raises(KernelError) as excinfo:
        await DeleteRole(access_ctx)(role_id=first.id)
    assert excinfo.value.code == "access.conflict"


async def test_bootstrap_administrator_enforces_single_admin(
    access_ctx: CommandContext,
    uow_factory: UoWFactory,
) -> None:
    from inc.capabilities.access.models import AccessSubjectRole

    first = await BootstrapAdministrator(access_ctx)(subject_type="identity", subject_id="u-1")
    # same subject is idempotent
    again = await BootstrapAdministrator(access_ctx)(subject_type="identity", subject_id="u-1")
    assert again.id == first.id
    # a second, different subject must be refused
    with pytest.raises(KernelError) as excinfo:
        await BootstrapAdministrator(access_ctx)(subject_type="identity", subject_id="u-2")
    assert excinfo.value.code == "access.administrator_exists"

    async with uow_factory() as uow:
        grants = (await uow.session.execute(select(AccessSubjectRole))).scalars().all()
    assert len(grants) == 1


async def test_diagnostics_report_unknown_keys(
    access_ctx: CommandContext,
    permissions: PermissionRegistry,
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    role = await CreateRole(access_ctx)(name="Rogue", slug="rogue")
    await ReplaceRoleCapabilities(access_ctx)(role_id=role.id, capability_keys=["content.publish"])
    # Introduce a stale key directly (simulates a removed registration).
    async with uow_factory() as uow:
        from inc.capabilities.access.models import AccessRole

        row = (
            (await uow.session.execute(select(AccessRole).where(AccessRole.slug == "rogue")))
            .scalars()
            .first()
        )
        from inc.kernel.db import JsonBModel  # noqa: F401

        stale = AccessRoleCapability(role_id=row.id, capability_key="ghost.key.removed")
        uow.session.add(stale)
        await uow.commit()

    diagnostics = AccessDiagnostics(uow_factory=uow_factory, permissions=permissions, clock=clock)
    results = await diagnostics.run()
    stale_result = next(r for r in results if r.code == "access.unknown_capability_keys")
    assert stale_result.status.value == "failed"
    admin_result = next(r for r in results if r.code == "access.no_admin_subjects")
    assert admin_result.status.value == "degraded"
