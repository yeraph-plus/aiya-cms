"""Idempotent RBAC role and permission seed."""

from collections.abc import Iterable

from inc.kernel.db import UoWExecutor

from .definitions import ROLE_SEEDS
from .models import Permission, Role
from .registry import CapabilityDefinition, capability_registry
from .uow import RBACUnitOfWork


async def seed_rbac(
    executor: UoWExecutor[RBACUnitOfWork],
    capabilities: Iterable[CapabilityDefinition] | None = None,
) -> None:
    """Create registered permissions plus the unchanged canonical roles and links."""

    definitions = capability_registry.definitions() if capabilities is None else tuple(capabilities)
    aliases = [definition.alias for definition in definitions]
    if len(aliases) != len(set(aliases)):
        raise RuntimeError("duplicate capability aliases passed to seed_rbac")
    missing_role_aliases = sorted(
        {alias for seed in ROLE_SEEDS for alias in seed.aliases}.difference(aliases)
    )
    if missing_role_aliases:
        raise RuntimeError(
            "canonical role aliases missing from capability seed: "
            + ", ".join(missing_role_aliases)
        )

    async def operation(uow: RBACUnitOfWork) -> None:
        permissions: dict[str, Permission] = {}
        for definition in definitions:
            permission = await uow.permissions.get_by_alias(definition.alias)
            if permission is None:
                permission = Permission(alias=definition.alias, description=definition.description)
                await uow.permissions.add(permission)
            permissions[definition.alias] = permission

        # Flush once so newly generated ids are available to association inserts.
        await uow.flush()
        for seed in ROLE_SEEDS:
            role = await uow.roles.get_by_name(seed.name)
            if role is None:
                role = Role(name=seed.name, description=seed.description)
                await uow.roles.add(role)
                await uow.flush()
            existing = await uow.rbac.permission_ids_for_role(role.id)
            missing = [
                permissions[alias].id
                for alias in seed.aliases
                if permissions[alias].id not in existing
            ]
            await uow.rbac.add_role_permissions(role.id, missing)

    await executor.write(operation)
