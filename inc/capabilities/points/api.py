"""Public points administration surface.

The composition root and HTTP adapters use semantic admin DTOs/services; ORM
models remain private to the capability implementation.
"""

from __future__ import annotations

from inc.capabilities.points.admin import (
    PointsAccountAdminRecordDTO,
    PointsAdminService,
    PointsProgramAdminDTO,
    PointsProgramInput,
    PointsProgramPatch,
    PointsProgramStatusInput,
    PointsSummaryAdminDTO,
)

__all__ = [
    "PointsAccountAdminRecordDTO",
    "PointsAdminService",
    "PointsProgramInput",
    "PointsProgramAdminDTO",
    "PointsProgramPatch",
    "PointsProgramStatusInput",
    "PointsSummaryAdminDTO",
]
