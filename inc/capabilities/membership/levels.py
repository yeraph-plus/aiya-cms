"""Membership level declarations and registry.

Contract source: context/spec/capabilities/membership.md §2.

MembershipLevelSpec is an immutable code declaration (like points
behaviors); the DB mirrors it for ops visibility and drift checks. Levels
are registered by the composition root (or by a feature), never discovered.
"""

from __future__ import annotations

import re

from inc.kernel.errors import ErrorCategory, KernelError

_LEVEL_KEY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


class MembershipLevelSpec:
    """Immutable declaration of a membership level."""

    __slots__ = (
        "key",
        "display_name",
        "tier_rank",
        "cycle_days",
        "grant_points",
        "renewal_allowed",
    )

    def __init__(
        self,
        *,
        key: str,
        display_name: str,
        tier_rank: int,
        cycle_days: int,
        grant_points: int,
        renewal_allowed: bool = True,
    ) -> None:
        if not _LEVEL_KEY.match(key):
            raise ValueError(f"invalid level key {key!r}")
        if not display_name:
            raise ValueError(f"level {key} requires a display name")
        if tier_rank <= 0:
            raise ValueError(f"level {key} tier_rank must be positive")
        if cycle_days <= 0:
            raise ValueError(f"level {key} cycle_days must be positive")
        if grant_points <= 0:
            raise ValueError(f"level {key} grant_points must be positive")
        self.key = key
        self.display_name = display_name
        self.tier_rank = tier_rank
        self.cycle_days = cycle_days
        self.grant_points = grant_points
        self.renewal_allowed = renewal_allowed


class MembershipLevelRegistry:
    """level key -> MembershipLevelSpec; frozen after boot."""

    def __init__(self) -> None:
        self._levels: dict[str, MembershipLevelSpec] = {}
        self._frozen = False

    def register(self, spec: MembershipLevelSpec) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"membership level registry is frozen; cannot register {spec.key}",
            )
        if spec.key in self._levels:
            raise KernelError(
                code="membership.duplicate_level",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate membership level {spec.key}",
            )
        self._levels[spec.key] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, key: str) -> MembershipLevelSpec:
        spec = self._levels.get(key)
        if spec is None:
            raise KernelError(
                code="membership.unknown_level",
                category=ErrorCategory.INTERNAL,
                message=f"membership level {key!r} is not registered",
            )
        return spec

    def specs(self) -> tuple[MembershipLevelSpec, ...]:
        return tuple(self._levels.values())
