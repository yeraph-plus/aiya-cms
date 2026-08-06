"""Mail outbox persistence model and DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TimestampMixin, new_uuid7


class MailStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    DEAD = "dead"


class MailContext(BaseModel):
    """Base JSONB context; registered templates provide a stricter model."""

    model_config = ConfigDict(extra="allow")


class MailOutbox(Base, TimestampMixin):
    __tablename__ = "mail_outbox"
    __table_args__ = (Index("ix_mail_outbox_status_attempts", "status", "attempts"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    to_addr: Mapped[str] = mapped_column(String(320), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    context: Mapped[MailContext] = mapped_column(JsonBModel(MailContext), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MailStatus.PENDING.value,
        server_default=MailStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MailOutboxRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    to_addr: str
    template: str
    context: MailContext
    status: MailStatus
    attempts: int
    last_error: str | None = None
    sent_at: datetime | None = None
    next_attempt_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
