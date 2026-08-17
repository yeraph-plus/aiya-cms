"""Membership capability: levels, subscription cycles, renewal and expiry.

Contract source: context/spec/capabilities/membership.md.

Public surface for the composition root: level registry, commands, queries,
diagnostics and the Ports consumed by this capability.
"""

from __future__ import annotations

from inc.capabilities.membership.admin import MembershipAdminService
from inc.capabilities.membership.commands import CommandContext, ExpireSubscription
from inc.capabilities.membership.diagnostics import MembershipDiagnostics
from inc.capabilities.membership.levels import (
    MembershipLevelRegistry,
    MembershipLevelSpec,
)
from inc.capabilities.membership.ports import (
    NullSubjectExists,
    PointsLedgerPort,
    RecordingPointsLedger,
    SubjectExistsPort,
)
from inc.capabilities.membership.queries import MembershipQueries

__all__ = [
    "CommandContext",
    "ExpireSubscription",
    "MembershipDiagnostics",
    "MembershipAdminService",
    "MembershipLevelRegistry",
    "MembershipLevelSpec",
    "MembershipQueries",
    "NullSubjectExists",
    "PointsLedgerPort",
    "RecordingPointsLedger",
    "SubjectExistsPort",
]
