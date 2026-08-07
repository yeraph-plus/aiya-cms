"""Points capability: programs, accounts, immutable ledger and behaviors.

Contract source: context/spec/capabilities/points.md.

Public surface for the composition root: behavior registry, commands,
queries and diagnostics.
"""

from __future__ import annotations

from inc.capabilities.points.behaviors import (
    PointBehaviorRegistry,
    PointBehaviorSpec,
)
from inc.capabilities.points.commands import CommandContext
from inc.capabilities.points.diagnostics import PointsDiagnostics
from inc.capabilities.points.queries import PointsQueries

__all__ = [
    "CommandContext",
    "PointBehaviorRegistry",
    "PointBehaviorSpec",
    "PointsDiagnostics",
    "PointsQueries",
]
