"""Assets persistence models.

Contract source: context/spec/capabilities/assets.md §3.

Only stable object references are stored; signed URLs are never
persisted. External object existence is confirmed by the provider, not
inferred from the local row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin

ASSET_STATES = ("pending", "ready", "failed", "deleted")


class AssetMetadata(BaseModel):
    """Schema-bound optional asset metadata."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = {}


@TableOwnership.owned_by("capability:assets")
class AssetObject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assets_objects"

    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[str | None] = mapped_column(String(200), nullable=True)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    alt_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    asset_metadata: Mapped[AssetMetadata] = mapped_column(
        JsonBModel(AssetMetadata, "1"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    external_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("provider_key", "object_key", name="uq_assets_provider_object"),
    )


@TableOwnership.owned_by("capability:assets")
class AssetUploadIntent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assets_upload_intents"

    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_subject_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    bucket: Mapped[str | None] = mapped_column(String(200), nullable=True)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    content_length_max: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_types: Mapped[str] = mapped_column(String(500), nullable=False)  # comma-joined allowlist
    checksum_sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
