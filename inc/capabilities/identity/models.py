"""Identity persistence models.

Contract source: context/spec/capabilities/identity.md §2.

Foreign keys exist only within this capability; ``avatar_asset_id`` is an
opaque reference to the assets capability and never a foreign key.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin


@TableOwnership.owned_by("capability:identity")
class IdentityUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "identity_users"

    username: Mapped[str] = mapped_column(String(100), nullable=False)
    username_normalized: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    email_display: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@TableOwnership.owned_by("capability:identity")
class IdentityLoginIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "identity_login_identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(320), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_subject", name="uq_identity_login_identity_provider_subject"
        ),
    )


@TableOwnership.owned_by("capability:identity")
class IdentityPasswordCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "identity_password_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    hash_version: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    compromised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@TableOwnership.owned_by("capability:identity")
class IdentityChallenge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "identity_challenges"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=5)

    __table_args__ = (Index("ix_identity_challenges_purpose_digest", "purpose", "token_digest"),)
