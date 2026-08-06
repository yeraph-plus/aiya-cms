"""OIDC-consumed Ports.

Contract source: context/spec/capabilities/oidc-provider.md §4.

These Protocols are defined here (the consumer) and implemented by the
composition root with identity/access adapters, or by test doubles.
"""

from __future__ import annotations

from typing import Any, Protocol


class SubjectAuthenticator(Protocol):
    """Validates the interactive login and returns the subject id."""

    async def authenticate(self, username: str, password: str) -> str | None: ...


class SubjectClaimsReader(Protocol):
    """Returns the minimal claims allowed by the authorized scopes."""

    async def claims_for(self, subject_id: str, scopes: set[str]) -> dict[str, Any]: ...


class AuthorizationDecisionReader(Protocol):
    """Whether the subject may be granted this scope/resource set."""

    async def can_grant(self, subject_id: str, client_id: str, scopes: set[str]) -> bool: ...


class SecurityEventSubscriber(Protocol):
    """Receives security facts (ban, password change) to revoke grants."""

    async def revoke_subject_sessions(self, subject_id: str, reason: str) -> None: ...


class SubjectExists(Protocol):
    """Validates opaque subject references (for admin client commands)."""

    async def exists(self, subject_type: str, subject_id: str) -> bool: ...
