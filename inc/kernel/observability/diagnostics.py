"""Diagnostics and admin readmodel contracts.

Contract source: context/spec/kernel/observability.md §3/§4.

Diagnostics are strictly read-only consistency and dependency checks: they
never repair, enqueue events, retry or refresh state. Results distinguish
``ok``, ``degraded``, ``failed`` and ``unavailable`` with a stable code.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
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

    async def summary(
        self, *, window: str = "7d", as_of: datetime | None = None
    ) -> dict[str, Any]: ...


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

    async def run_all(
        self, *, window: str = "7d", as_of: datetime | None = None
    ) -> dict[str, dict[str, Any]]:
        """Run enabled providers concurrently with bounded isolation.

        A provider is a read-only projection boundary.  It must not make the
        dashboard request fail when it times out or raises, and a slow
        provider must not consume an unbounded number of tasks.
        """

        captured_as_of = as_of or datetime.now(UTC)
        semaphore = asyncio.Semaphore(4)

        async def invoke(key: str, provider: AdminSummaryProvider) -> tuple[str, dict[str, Any]]:
            async with semaphore:
                try:
                    method = provider.summary
                    parameters = inspect.signature(method).parameters
                    kwargs: dict[str, Any] = {}
                    if "window" in parameters:
                        kwargs["window"] = window
                    if "as_of" in parameters:
                        kwargs["as_of"] = captured_as_of
                    value = await asyncio.wait_for(method(**kwargs), timeout=2.0)
                    return key, value
                except Exception:  # noqa: BLE001 - isolate one provider
                    return key, {"unavailable": True}

        pairs = await asyncio.gather(
            *(invoke(key, self._providers[key]) for key in sorted(self._providers))
        )
        return dict(pairs)
