"""Membership capability: levels, subscription cycles, renewal and expiry.

Contract source: context/spec/capabilities/membership.md.

Public surface for the composition root: level registry, commands, queries,
diagnostics and the Ports consumed by this capability.
"""

from __future__ import annotations

from inc.capabilities.membership.admin import MembershipAdminService
from inc.capabilities.membership.commands import (
    AttachPointsGrant,
    CancelSubscription,
    CommandContext,
    ExpireSubscription,
    MarkCycleFailed,
    PrepareSubscriptionCycle,
    TerminateSubscription,
)
from inc.capabilities.membership.diagnostics import MembershipDiagnostics
from inc.capabilities.membership.levels import (
    MembershipLevelRegistry,
    MembershipLevelSpec,
)
from inc.capabilities.membership.queries import MembershipQueries
from inc.capabilities.membership.schemas import (
    AttachPointsGrantInput,
    CancelInput,
    MarkCycleFailedInput,
    MembershipCycleDTO,
    PrepareSubscriptionCycleInput,
    SubscriptionDTO,
    TerminateInput,
)

__all__ = [
    "AttachPointsGrant",
    "AttachPointsGrantInput",
    "CancelInput",
    "CancelSubscription",
    "CommandContext",
    "ExpireSubscription",
    "MarkCycleFailed",
    "MarkCycleFailedInput",
    "MembershipCycleDTO",
    "MembershipDiagnostics",
    "MembershipAdminService",
    "MembershipLevelRegistry",
    "MembershipLevelSpec",
    "MembershipQueries",
    "PrepareSubscriptionCycle",
    "PrepareSubscriptionCycleInput",
    "SubscriptionDTO",
    "TerminateSubscription",
    "TerminateInput",
]
