"""Append-only audit persistence model and query DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, new_uuid7


class AuditContext(BaseModel):
    reason: str | None = None
    extra: dict[str, str] | None = None


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_action_time", "action", "created_at"),
        Index("ix_audit_logs_actor_time", "actor_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    context: Mapped[AuditContext | None] = mapped_column(JsonBModel(AuditContext), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_type: str
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    context: AuditContext | None
    ip: str | None
    created_at: datetime


class AuditQuery(BaseModel):
    action: str | None = Field(default=None, max_length=64)
    actor_id: uuid.UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
