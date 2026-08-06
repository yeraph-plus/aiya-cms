"""Access DTOs and Ports.

Contract source: context/spec/capabilities/access.md §5/§6.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class RoleDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    slug: str
    description: str | None = None
    system: bool = False
    capability_keys: list[str] = Field(default_factory=list)


class Principal(BaseModel):
    """Authenticated caller; never carries ORM objects or secrets."""

    model_config = ConfigDict(extra="forbid")

    subject_id: str
    status: str = "active"
    auth_method: str = "unknown"
    session_id: str | None = None
    client_id: str | None = None
    capabilities: set[str] = Field(default_factory=set)


class AuthorizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str = "deny.default"


class SubjectExists(Protocol):
    """Validates opaque subject references before role assignment."""

    async def exists(self, subject_type: str, subject_id: str) -> bool: ...


class GrantSummary(BaseModel):
    """Role grants for one subject (used by read surfaces)."""

    model_config = ConfigDict(extra="forbid")

    subject_type: str
    subject_id: str
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
