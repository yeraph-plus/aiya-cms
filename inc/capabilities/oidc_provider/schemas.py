"""OIDC DTOs and error model.

Contract source: context/spec/capabilities/oidc-provider.md §3/§7.

Protocol errors use OAuth/OIDC standard error codes, not the business error
DTO. Details never leak tokens, codes or secrets.
"""

from __future__ import annotations

from dataclasses import field
from typing import Literal

from pydantic import BaseModel, ConfigDict

OidcErrorCode = Literal[
    "invalid_request",
    "invalid_client",
    "invalid_grant",
    "invalid_scope",
    "unauthorized_client",
    "unsupported_response_type",
    "unsupported_grant_type",
    "access_denied",
    "server_error",
    "temporarily_unavailable",
    "invalid_token",
    "unsupported_token_type",
]


class OidcError(Exception):
    """OAuth/OIDC protocol error: standard code + optional description."""

    def __init__(
        self,
        code: OidcErrorCode,
        description: str | None = None,
        http_status: int = 400,
    ) -> None:
        super().__init__(description or code)
        self.code = code
        self.description = description
        self.http_status = http_status

    def __str__(self) -> str:
        return self.description or self.code


class ClientDTO(BaseModel):
    """Admin-visible client registration (never contains secrets)."""

    model_config = ConfigDict(extra="forbid")

    client_id: str
    client_type: str
    name: str
    redirect_uris: list[str]
    post_logout_redirect_uris: list[str] = field(default_factory=list)
    allowed_scopes: list[str]
    allowed_audiences: list[str] = field(default_factory=list)
    auth_method: str = "none"
    grant_types: list[str] = field(default_factory=lambda: ["authorization_code"])
    response_types: list[str] = field(default_factory=lambda: ["code"])
    status: str = "active"
    trusted: bool = False
    allow_refresh: bool = True


class ClientRegistrationResult(BaseModel):
    """Result of client registration; secret shown exactly once."""

    model_config = ConfigDict(extra="forbid")

    client: ClientDTO
    client_secret: str | None = None


class TokenResponse(BaseModel):
    """OAuth token response body."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 300
    scope: str | None = None
    id_token: str | None = None
    refresh_token: str | None = None


class IntrospectionResult(BaseModel):
    """Minimal introspection of a refresh token (internal use)."""

    model_config = ConfigDict(extra="forbid")

    active: bool
    subject_id: str | None = None
    client_id: str | None = None
