"""Typed build registry with validate/freeze/report.

Contract source: context/spec/kernel/boot.md.

A Registry is a container-local build object: entries are added only during
the boot build phase, validated, then frozen. After freeze, mutation raises
``kernel.registry_frozen`` and unknown lookups raise a stable error — never
an automatic import. Reports are sorted and contain no secrets.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from inc.kernel.errors import ErrorCategory, KernelError


@dataclass(frozen=True, slots=True)
class RegistryEntry[T]:
    key: str
    owner: str
    value: T
    version: str = "1"
    dependencies: tuple[str, ...] = ()


class Registry[T]:
    """Typed key -> value registry for one registration category."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._entries: dict[str, RegistryEntry[T]] = {}
        self._frozen = False

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(
        self,
        key: str,
        value: T,
        *,
        owner: str,
        version: str = "1",
        dependencies: Iterable[str] = (),
    ) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"{self._kind} registry is frozen; cannot register {key}",
            )
        if key in self._entries:
            raise KernelError(
                code="kernel.registry_duplicate",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate {self._kind} key {key}",
            )
        self._entries[key] = RegistryEntry(
            key=key,
            owner=owner,
            value=value,
            version=version,
            dependencies=tuple(dependencies),
        )

    def lookup(self, key: str) -> T:
        entry = self._entries.get(key)
        if entry is None:
            raise KernelError(
                code="kernel.registry_unknown",
                category=ErrorCategory.INTERNAL,
                message=f"unknown {self._kind} key {key}",
            )
        return entry.value

    def get(self, key: str) -> T | None:
        entry = self._entries.get(key)
        return entry.value if entry is not None else None

    def validate(self) -> list[str]:
        """Return unresolved dependency problems; empty means valid."""

        problems: list[str] = []
        for key, entry in self._entries.items():
            for dependency in entry.dependencies:
                if dependency not in self._entries:
                    problems.append(f"{key} depends on unregistered {dependency}")
        return problems

    def freeze(self) -> None:
        self._frozen = True

    def report(self) -> tuple[str, ...]:
        """Deterministic, secret-free registration summary."""

        lines = [
            f"{self._kind} {entry.key} owner={entry.owner} version={entry.version}"
            + (f" deps={','.join(entry.dependencies)}" if entry.dependencies else "")
            for entry in sorted(self._entries.values(), key=lambda e: e.key)
        ]
        return tuple(lines)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def items(self) -> tuple[tuple[str, RegistryEntry[T]], ...]:
        return tuple(sorted(self._entries.items()))

    def __len__(self) -> int:
        return len(self._entries)
