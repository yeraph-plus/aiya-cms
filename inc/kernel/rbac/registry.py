"""Explicit Capability alias and Policy registration."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from inc.kernel.errors import AppError
from inc.kernel.security import Principal

from .errors import RBAC_003
from .schemas import PolicyContext

Policy = Callable[[Principal, PolicyContext | None], bool]
_CAPABILITY_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    alias: str
    description: str
    policy: Policy | None = None
    audited: bool = False


class CapabilityRegistry:
    """Process-wide explicit capability registry."""

    def __init__(self) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}
        self._frozen = False

    def register(self, definition: CapabilityDefinition) -> None:
        if self._frozen:
            raise RuntimeError("capability registry is frozen")
        if (
            len(definition.alias) > 64
            or _CAPABILITY_ALIAS_PATTERN.fullmatch(definition.alias) is None
        ):
            raise ValueError(f"invalid capability alias: {definition.alias}")
        if not definition.description.strip() or len(definition.description) > 256:
            raise ValueError("capability description must be 1-256 characters")
        if definition.alias in self._definitions:
            raise ValueError(f"duplicate capability alias: {definition.alias}")
        self._definitions[definition.alias] = definition

    def register_many(self, definitions: Iterable[CapabilityDefinition]) -> None:
        for definition in definitions:
            self.register(definition)

    def reset(self) -> None:
        self._definitions.clear()
        self._frozen = False

    def has(self, alias: str) -> bool:
        return alias in self._definitions

    def get(self, alias: str) -> CapabilityDefinition:
        try:
            return self._definitions[alias]
        except KeyError as exc:
            raise AppError(RBAC_003, detail={"alias": alias}) from exc

    def aliases(self) -> frozenset[str]:
        return frozenset(self._definitions)

    def definitions(self) -> tuple[CapabilityDefinition, ...]:
        return tuple(self._definitions.values())

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def freeze(self) -> None:
        self._frozen = True

    def validate(self, aliases: Iterable[str] | None = None) -> None:
        missing = [alias for alias in (aliases or ()) if alias not in self._definitions]
        if missing:
            raise RuntimeError(f"unregistered capability aliases: {', '.join(sorted(missing))}")


capability_registry = CapabilityRegistry()


def register_capability(definition: CapabilityDefinition) -> None:
    """Register one explicitly wired downstream Capability definition."""

    capability_registry.register(definition)


def register_capabilities(*definitions: CapabilityDefinition) -> None:
    """Register explicitly wired downstream Capability definitions in order."""

    capability_registry.register_many(definitions)


def validate_capability_registry(aliases: Iterable[str] | None = None) -> None:
    """Fail-fast startup check for explicitly required aliases."""

    capability_registry.validate(aliases if aliases is not None else capability_registry.aliases())
