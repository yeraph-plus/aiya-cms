"""Permission key registry.

Contract source: context/spec/capabilities/access.md §2.

Capabilities and features declare the permission keys they own; the
composition root registers them into a container-local PermissionRegistry
before boot. Duplicate keys or keys whose owner prefix does not match the
declaring capability fail fast. Unregistered keys can never be bound to
routers or commands.
"""

from __future__ import annotations

import re

from inc.kernel.errors import ErrorCategory, KernelError

_KEY = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


def validate_permission_key(key: str) -> None:
    if not _KEY.match(key):
        raise ValueError(f"invalid permission key {key!r}: expected dotted lowercase key")


class PermissionRegistry:
    """permission key -> owning capability; frozen after boot."""

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self._frozen = False

    def register(self, key: str, *, owner: str) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"permission registry is frozen; cannot register {key}",
            )
        validate_permission_key(key)
        if key in self._keys:
            raise KernelError(
                code="kernel.registry_duplicate",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate permission key {key}",
            )
        if not key.startswith(f"{owner}."):
            raise KernelError(
                code="kernel.registry_invalid",
                category=ErrorCategory.INTERNAL,
                message=f"permission {key} is not owned by {owner}",
            )
        self._keys[key] = owner

    def register_declared(self, owner: str, declared: tuple[str, ...]) -> None:
        for key in declared:
            self.register(key, owner=owner)

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def contains(self, key: str) -> bool:
        return key in self._keys

    def require(self, key: str) -> None:
        if not self.contains(key):
            raise KernelError(
                code="kernel.registry_unknown",
                category=ErrorCategory.INTERNAL,
                message=f"permission {key} is not registered",
            )

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._keys))
