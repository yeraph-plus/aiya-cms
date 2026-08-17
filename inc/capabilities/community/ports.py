"""Ports consumed by community."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from inc.capabilities.community.schemas import CommunityAuthorDTO


class CommunityAuthorReference(Protocol):
    author_type: str
    author_id: str


class CommunityAuthorPort(Protocol):
    """Validate opaque author references and return safe public projections."""

    async def validate(self, author_type: str, author_id: str) -> bool: ...

    async def project(
        self, references: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], CommunityAuthorDTO]: ...
