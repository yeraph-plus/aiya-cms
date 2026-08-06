"""Contracts for explicit downstream Capability registration (ADR-0033)."""

from typing import Any
from uuid import uuid4

import pytest

from inc.kernel.rbac import (
    ALL_CAPABILITIES,
    ROLE_SEEDS,
    CapabilityDefinition,
    capability_registry,
    register_capabilities,
    register_capability,
    seed_rbac,
)
from inc.kernel.rbac.models import Permission, Role


@pytest.fixture(autouse=True)
def fresh_capability_registry() -> None:
    capability_registry.reset()
    capability_registry.register_many(ALL_CAPABILITIES)
    yield
    capability_registry.reset()
    capability_registry.register_many(ALL_CAPABILITIES)


def test_downstream_registration_does_not_mutate_canonical_role_templates() -> None:
    canonical_roles = tuple((seed.name, seed.aliases) for seed in ROLE_SEEDS)
    definitions = (
        CapabilityDefinition("sample:read", "读取下游样例"),
        CapabilityDefinition("sample:operate", "操作下游样例", audited=True),
    )

    register_capabilities(*definitions)

    assert capability_registry.definitions()[-2:] == definitions
    assert capability_registry.get("sample:operate") == definitions[1]
    assert tuple((seed.name, seed.aliases) for seed in ROLE_SEEDS) == canonical_roles
    assert all("sample:read" not in seed.aliases for seed in ROLE_SEEDS)
    assert all("sample:operate" not in seed.aliases for seed in ROLE_SEEDS)


def test_downstream_registration_validates_duplicates_and_freezes() -> None:
    definition = CapabilityDefinition("sample:operate", "操作下游样例")
    register_capability(definition)

    with pytest.raises(ValueError, match="duplicate capability alias"):
        register_capability(definition)
    with pytest.raises(ValueError, match="invalid capability alias"):
        register_capability(CapabilityDefinition("sample-operate", "非法别名"))
    with pytest.raises(ValueError, match="description"):
        register_capability(CapabilityDefinition("sample:empty", ""))

    capability_registry.freeze()
    assert capability_registry.is_frozen
    with pytest.raises(RuntimeError, match="frozen"):
        register_capability(CapabilityDefinition("sample:late", "过晚登记"))


class _Permissions:
    def __init__(self) -> None:
        self.items: dict[str, Permission] = {}

    async def get_by_alias(self, alias: str) -> Permission | None:
        return self.items.get(alias)

    async def add(self, permission: Permission) -> None:
        self.items[permission.alias] = permission


class _Roles:
    def __init__(self) -> None:
        self.items: dict[str, Role] = {}

    async def get_by_name(self, name: str) -> Role | None:
        return self.items.get(name)

    async def add(self, role: Role) -> None:
        self.items[role.name] = role


class _RolePermissions:
    def __init__(self) -> None:
        self.items: dict[Any, set[Any]] = {}

    async def permission_ids_for_role(self, role_id: Any) -> set[Any]:
        return set(self.items.get(role_id, set()))

    async def add_role_permissions(self, role_id: Any, permission_ids: list[Any]) -> None:
        self.items.setdefault(role_id, set()).update(permission_ids)


class _RBACUoW:
    def __init__(self) -> None:
        self.permissions = _Permissions()
        self.roles = _Roles()
        self.rbac = _RolePermissions()

    async def flush(self) -> None:
        for item in (*self.permissions.items.values(), *self.roles.items.values()):
            if getattr(item, "id", None) is None:
                item.id = uuid4()


class _WriteExecutor:
    def __init__(self, uow: _RBACUoW) -> None:
        self.uow = uow

    async def write(self, operation: Any) -> Any:
        return await operation(self.uow)


async def test_seed_syncs_registered_permission_without_changing_default_roles() -> None:
    register_capability(CapabilityDefinition("sample:operate", "操作下游样例"))
    uow = _RBACUoW()

    await seed_rbac(_WriteExecutor(uow))  # type: ignore[arg-type]

    downstream_id = uow.permissions.items["sample:operate"].id
    assert all(downstream_id not in permission_ids for permission_ids in uow.rbac.items.values())
    for seed in ROLE_SEEDS:
        role_id = uow.roles.items[seed.name].id
        expected_ids = {uow.permissions.items[alias].id for alias in seed.aliases}
        assert uow.rbac.items[role_id] == expected_ids
