"""OIDC persistence models.

Contract source: context/spec/capabilities/oidc-provider.md §5.

Every code, refresh token, session handle and client secret is stored as a
digest. Signing private keys never enter the database; only public JWK and
lifecycle metadata do. Subjects are opaque references without foreign keys.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin


class StringList(BaseModel):
    """Bound JsonBModel list payload."""

    model_config = ConfigDict(extra="forbid")

    items: list[str] = Field(default_factory=list)


class PublicJwk(BaseModel):
    """Bound JsonBModel public JWK payload."""

    model_config = ConfigDict(extra="forbid")

    kty: str = "RSA"
    kid: str
    alg: str = "RS256"
    use: str = "sig"
    n: str
    e: str


@TableOwnership.owned_by("capability:oidc_provider")
class OidcClient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oidc_clients"

    client_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    client_type: Mapped[str] = mapped_column(String(16), nullable=False)  # public | confidential
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    redirect_uris: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    post_logout_redirect_uris: Mapped[StringList] = mapped_column(
        JsonBModel(StringList, "1"), nullable=False
    )
    allowed_scopes: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    allowed_audiences: Mapped[StringList] = mapped_column(
        JsonBModel(StringList, "1"), nullable=False
    )
    auth_method: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    grant_types: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    response_types: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )  # active | disabled
    trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_refresh: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


@TableOwnership.owned_by("capability:oidc_provider")
class OidcClientSecret(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oidc_client_secrets"

    client_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    secret_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@TableOwnership.owned_by("capability:oidc_provider")
class OidcAuthorizationCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oidc_authorization_codes"

    code_digest: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    client_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    scopes: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    audiences: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    nonce: Mapped[str | None] = mapped_column(String(500), nullable=True)
    code_challenge: Mapped[str | None] = mapped_column(String(200), nullable=True)
    code_challenge_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@TableOwnership.owned_by("capability:oidc_provider")
class OidcGrantConsent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oidc_grants_consents"

    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    scopes: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    audiences: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("subject_id", "client_id", name="uq_oidc_grant_subject_client"),
    )


@TableOwnership.owned_by("capability:oidc_provider")
class OidcSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oidc_sessions"

    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    session_handle: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    auth_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acr: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    amr: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@TableOwnership.owned_by("capability:oidc_provider")
class OidcRefreshFamily(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oidc_refresh_families"

    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@TableOwnership.owned_by("capability:oidc_provider")
class OidcRefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oidc_refresh_tokens"

    family_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("oidc_refresh_families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_digest: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scopes: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    audiences: Mapped[StringList] = mapped_column(JsonBModel(StringList, "1"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inactivity_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@TableOwnership.owned_by("capability:oidc_provider")
class OidcSigningKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oidc_signing_keys"

    kid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    algorithm: Mapped[str] = mapped_column(String(16), nullable=False, default="RS256")
    public_jwk: Mapped[PublicJwk] = mapped_column(JsonBModel(PublicJwk, "1"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )  # active | retired
    not_before_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delete_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_oidc_signing_keys_status", "status"),)
