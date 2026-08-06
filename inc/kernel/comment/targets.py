"""Target protocols and policy projection for polymorphic comments."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class CommentTargetPolicy:
    """Policy projected from a registered content declaration."""

    allow: bool = True
    max_depth: int = 3
    auto_approve: bool = False
    rate_limit: int = 10
    data_model: type[BaseModel] = BaseModel

    def __post_init__(self) -> None:
        if self.max_depth < 0:
            raise ValueError("comment max_depth must be non-negative")
        if self.rate_limit < 1:
            raise ValueError("comment rate_limit must be positive")


TargetExists = Callable[[str, UUID], bool | Awaitable[bool]]
TargetPolicyResolver = Callable[[str], CommentTargetPolicy | None]
