"""Diagnostics and admin readmodel contracts.

Contract source: context/spec/kernel/observability.md §3/§4.

Diagnostics are strictly read-only consistency and dependency checks: they
never repair, enqueue events, retry or refresh state. Results distinguish
``ok``, ``degraded``, ``failed`` and ``unavailable`` with a stable code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class DiagnosticStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DiagnosticResult:
    code: str
    status: DiagnosticStatus
    summary: str

    @property
    def healthy(self) -> bool:
        return self.status in (DiagnosticStatus.OK, DiagnosticStatus.DEGRADED)


class DiagnosticProvider(Protocol):
    """Read-only consistency probe registered by a capability or kernel."""

    key: str

    async def run(self) -> Sequence[DiagnosticResult]: ...


class DiagnosticRegistry:
    """Aggregates enabled diagnostic providers; frozen after boot."""

    def __init__(self) -> None:
        self._providers: dict[str, DiagnosticProvider] = {}
        self._frozen = False

    def register(self, provider: DiagnosticProvider) -> None:
        if self._frozen:
            raise RuntimeError("diagnostic registry is frozen")
        if provider.key in self._providers:
            raise ValueError(f"duplicate diagnostic provider {provider.key!r}")
        self._providers[provider.key] = provider

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    async def run_all(self) -> tuple[DiagnosticResult, ...]:
        results: list[DiagnosticResult] = []
        for key in sorted(self._providers):
            try:
                results.extend(await self._providers[key].run())
            except Exception as exc:  # noqa: BLE001 - diagnostics never crash the probe
                results.append(
                    DiagnosticResult(
                        code=f"kernel.diagnostics.{key}",
                        status=DiagnosticStatus.UNAVAILABLE,
                        summary=f"provider failed: {type(exc).__name__}",
                    )
                )
        return tuple(sorted(results, key=lambda r: r.code))


class AdminSummaryProvider(Protocol):
    """Aggregation DTO for the admin summary surface."""

    key: str

    async def summary(self) -> dict[str, Any]: ...


class AdminSummaryRegistry:
    """Aggregates enabled summary providers; frozen after boot."""

    def __init__(self) -> None:
        self._providers: dict[str, AdminSummaryProvider] = {}
        self._frozen = False

    def register(self, provider: AdminSummaryProvider) -> None:
        if self._frozen:
            raise RuntimeError("admin summary registry is frozen")
        if provider.key in self._providers:
            raise ValueError(f"duplicate admin summary provider {provider.key!r}")
        self._providers[provider.key] = provider

    def freeze(self) -> None:
        self._frozen = True

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    async def run_all(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for key in sorted(self._providers):
            try:
                out[key] = await self._providers[key].summary()
            except Exception:  # noqa: BLE001 - surface per-provider failure distinctly
                out[key] = {"unavailable": True}
        return out
