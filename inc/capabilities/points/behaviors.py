"""Points behavior declarations and registry.

Contract source: context/spec/capabilities/points.md §4.

PointBehaviorSpec is an immutable code declaration registered by features;
points executes the generic constraints, features decide when to call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel

from inc.kernel.errors import ErrorCategory, KernelError

_KEY = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")
_PROGRAM_KEY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
DIRECTIONS = ("credit", "debit")
DEFAULT_METADATA = BaseModel


@dataclass(frozen=True, slots=True)
class PointBehaviorSpec:
    """Immutable declaration of a points behavior."""

    key: str
    version: str
    program_key: str
    direction: str
    fixed_amount: int | None = None
    min_amount: int = 1
    max_amount: int = 1_000_000
    cooldown_seconds: int | None = None
    daily_limit: int | None = None
    business_timezone: str = "UTC"
    expiration_days: int | None = None
    metadata_schema: type[BaseModel] = DEFAULT_METADATA
    allowed_source_types: tuple[str, ...] = ("content", "payment", "system")
    allowed_actor_types: tuple[str, ...] = ("user", "system")
    required_access_key: str | None = None

    def __post_init__(self) -> None:
        if not _KEY.match(self.key):
            raise ValueError(f"invalid behavior key {self.key!r}")
        if not self.version:
            raise ValueError(f"behavior {self.key} requires a version")
        if not _PROGRAM_KEY.match(self.program_key):
            raise ValueError(f"behavior {self.key} declares invalid program key")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"behavior {self.key} has invalid direction {self.direction!r}")
        if self.fixed_amount is not None and self.fixed_amount <= 0:
            raise ValueError(f"behavior {self.key} fixed_amount must be positive")
        if not (1 <= self.min_amount <= self.max_amount):
            raise ValueError(f"behavior {self.key} has invalid amount range")
        if self.cooldown_seconds is not None and self.cooldown_seconds <= 0:
            raise ValueError(f"behavior {self.key} cooldown must be positive")
        if self.daily_limit is not None and self.daily_limit <= 0:
            raise ValueError(f"behavior {self.key} daily_limit must be positive")
        if self.expiration_days is not None and self.expiration_days <= 0:
            raise ValueError(f"behavior {self.key} expiration_days must be positive")
        if self.direction == "debit" and self.expiration_days is not None:
            raise ValueError(f"behavior {self.key} cannot combine debit with expiration_days")
        if not isinstance(self.metadata_schema, type) or not issubclass(
            self.metadata_schema, BaseModel
        ):
            raise ValueError(f"behavior {self.key} requires a Pydantic metadata schema")


class PointBehaviorRegistry:
    """behavior key -> PointBehaviorSpec; frozen after boot."""

    def __init__(self) -> None:
        self._behaviors: dict[str, PointBehaviorSpec] = {}
        self._frozen = False

    def register(self, spec: PointBehaviorSpec) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"points behavior registry is frozen; cannot register {spec.key}",
            )
        if spec.key in self._behaviors:
            raise KernelError(
                code="points.duplicate_behavior",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate points behavior {spec.key}",
            )
        self._behaviors[spec.key] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, key: str) -> PointBehaviorSpec:
        spec = self._behaviors.get(key)
        if spec is None:
            raise KernelError(
                code="points.unknown_behavior",
                category=ErrorCategory.INTERNAL,
                message=f"points behavior {key!r} is not registered",
            )
        return spec

    def specs(self) -> tuple[PointBehaviorSpec, ...]:
        return tuple(self._behaviors.values())
