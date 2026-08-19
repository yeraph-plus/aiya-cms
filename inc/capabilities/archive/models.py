"""Archive capability persistence models.

Contract source: ``context/spec/capabilities/archive.md`` sections 2 and 3.

The external locator is deliberately a capability-internal Pydantic value. It
is never copied to a public DTO, event, delivery attempt or content snapshot.
There are no foreign keys to another capability's tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin

ARCHIVE_ITEM_STATES = ("pending", "active", "unavailable", "retired")
ARCHIVE_GRANT_STATES = ("pending", "active", "expired", "revoked", "failed")
ARCHIVE_DELIVERY_ATTEMPT_STATES = (
    "pending",
    "delivered",
    "proxy_required",
    "failed",
    "expired",
    "revoked",
    "unknown",
)

ITEM_STATES = ARCHIVE_ITEM_STATES
GRANT_STATES = ARCHIVE_GRANT_STATES
DELIVERY_ATTEMPT_STATES = ARCHIVE_DELIVERY_ATTEMPT_STATES

ARCHIVE_PART_PROFILE_KEY = "archive.part.4g.v1"
ARCHIVE_PART_MAX_BYTES = 4 * 1024 * 1024 * 1024


class ArchiveExternalLocator(BaseModel):
    """Protected provider locator; only its owning adapter may interpret it."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=4096)
    schema_version: str = Field(default="1", min_length=1, max_length=32)

    @field_validator("value")
    @classmethod
    def _not_a_url_or_header(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if not value or parsed.scheme or value.startswith("//"):
            raise ValueError("archive locator must be a provider reference, not a URL")
        if any(character in value for character in ("\x00", "\r", "\n")):
            raise ValueError("archive locator contains a forbidden control character")
        return value


class ArchiveItemSnapshot(BaseModel):
    """Immutable public facts captured when a grant is issued."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=200)
    item_key: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    provider_key: str = Field(min_length=1, max_length=64)
    part_number: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=500)
    size_bytes: int = Field(gt=0)
    checksum_algorithm: str | None = Field(default=None, max_length=32)
    checksum_value: str | None = Field(default=None, max_length=256)


class ArchiveGrantSnapshot(BaseModel):
    """Versioned grant item snapshot; it contains no locator or delivery data."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1", min_length=1, max_length=32)
    manifest_version: str = Field(min_length=1, max_length=64)
    manifest_digest: str = Field(min_length=1, max_length=128)
    items: tuple[ArchiveItemSnapshot, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_parts(self) -> ArchiveGrantSnapshot:
        parts = [item.part_number for item in self.items]
        if len(parts) != len(set(parts)):
            raise ValueError("part_number must be unique in a grant snapshot")
        return self


@TableOwnership.owned_by("capability:archive")
class ArchiveItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "archive_items"

    item_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    external_locator: Mapped[ArchiveExternalLocator] = mapped_column(
        JsonBModel(ArchiveExternalLocator, "1"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_algorithm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    checksum_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    provider_fact_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unavailable_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_archive_items_size_positive"),
        CheckConstraint(
            f"size_bytes <= {ARCHIVE_PART_MAX_BYTES}",
            name="ck_archive_items_size_at_most_4g",
        ),
        CheckConstraint("part_number > 0", name="ck_archive_items_part_positive"),
        CheckConstraint(
            "state IN ('pending', 'active', 'unavailable', 'retired')",
            name="ck_archive_items_state",
        ),
        CheckConstraint("version >= 1", name="ck_archive_items_version"),
        Index("ix_archive_items_part_state", "part_number", "state"),
    )


@TableOwnership.owned_by("capability:archive")
class ArchiveDownloadGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "archive_download_grants"

    subject_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    product_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quote_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    points_entry_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(200), nullable=False)
    manifest_version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    item_snapshot: Mapped[ArchiveGrantSnapshot] = mapped_column(
        JsonBModel(ArchiveGrantSnapshot, "1"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key_digest: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'expired', 'revoked', 'failed')",
            name="ck_archive_grants_state",
        ),
        CheckConstraint("version >= 1", name="ck_archive_grants_version"),
        CheckConstraint("expires_at > valid_from", name="ck_archive_grants_window"),
        Index("ix_archive_grants_subject_status", "subject_type", "subject_id", "status"),
    )

    @property
    def granted_items_snapshot(self) -> ArchiveGrantSnapshot:
        """Descriptive alias used by the public capability language."""

        return self.item_snapshot


@TableOwnership.owned_by("capability:archive")
class ArchiveDeliveryAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "archive_delivery_attempts"

    grant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_delivery_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    link_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="ck_archive_attempt_number_positive"),
        CheckConstraint(
            "status IN ("
            "'pending', 'delivered', 'proxy_required', 'failed', "
            "'expired', 'revoked', 'unknown')",
            name="ck_archive_attempt_state",
        ),
        Index(
            "uq_archive_attempt_number",
            "grant_id",
            "item_id",
            "attempt_number",
            unique=True,
        ),
    )
