"""Points capability: programs, accounts, immutable ledger, buckets and
behaviors.

Contract source: context/spec/capabilities/points.md.

Public surface for the composition root: behavior registry, commands,
queries and diagnostics.
"""

from __future__ import annotations

from inc.capabilities.points.admin import (
    PointsAdminService,
    PointsProgramInput,
    PointsProgramPatch,
    PointsProgramStatusInput,
)
from inc.capabilities.points.behaviors import (
    PointBehaviorRegistry,
    PointBehaviorSpec,
)
from inc.capabilities.points.commands import (
    CommandContext,
    ExpireBuckets,
)
from inc.capabilities.points.constants import DEFAULT_PROGRAM_KEY
from inc.capabilities.points.diagnostics import PointsDiagnostics
from inc.capabilities.points.queries import PointsQueries

__all__ = [
    "CommandContext",
    "DEFAULT_PROGRAM_KEY",
    "ExpireBuckets",
    "PointBehaviorRegistry",
    "PointBehaviorSpec",
    "PointsAdminService",
    "PointsProgramInput",
    "PointsProgramPatch",
    "PointsProgramStatusInput",
    "PointsDiagnostics",
    "PointsQueries",
]
