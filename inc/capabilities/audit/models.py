"""Audit persistence model.

Contract source: context/spec/capabilities/audit.md §3.

Entries are immutable: no update or delete is exposed. Deduplication is
enforced by the unique envelope id plus the inbox receipt.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin


class AuditMetadata(BaseModel):
    """Bound JsonBModel payload for safe, schema-versioned audit metadata."""

    schema_version: str = "1"
    data: dict[str, object] = Field(default_factory=dict)


@TableOwnership.owned_by("capability:audit")
class AuditEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_entries"

    envelope_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    action: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    client_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    session_handle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    details: Mapped[AuditMetadata] = mapped_column(JsonBModel(AuditMetadata, "1"), nullable=False)

    __table_args__ = (Index("ix_audit_entries_window", "occurred_at", "action"),)
