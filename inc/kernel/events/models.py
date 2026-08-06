"""Kernel outbox and inbox tables.

Contract source: context/spec/kernel/events.md §3/§4, kernel/README.md.

These are the only kernel-owned event tables; business events never get
their own kernel persistence. Status values are stable strings:
outbox ``pending``/``claimed``/``delivered``/``dead``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin
from inc.kernel.events.envelope import EventEnvelope


@TableOwnership.owned_by("kernel:events")
class OutboxMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "kernel_outbox"

    event_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    envelope: Mapped[EventEnvelope] = mapped_column(JsonBModel(EventEnvelope, "1"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (Index("ix_kernel_outbox_due", "status", "next_attempt_at"),)


@TableOwnership.owned_by("kernel:events")
class InboxReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "kernel_inbox_receipts"

    handler_key: Mapped[str] = mapped_column(String(200), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("handler_key", "event_id", name="uq_kernel_inbox_receipts_handler_event"),
        Index("ix_kernel_inbox_receipts_handler", "handler_key"),
    )
