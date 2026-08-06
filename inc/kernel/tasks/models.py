"""Task and Cron persistence models (kernel-owned tables).

Contract source: context/spec/kernel/workflow-tasks.md §2/§6.

Payload and results are versioned Pydantic payloads; lease fields allow
multi-worker claims and crash recovery. Status strings are stable:
``pending``/``claimed``/``completed``/``failed``/``dead``/``cancelled``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin
from inc.kernel.workflow.models import VersionedState


class TaskPayload(BaseModel):
    """Versioned payload for a task instance."""

    schema_version: str
    data: dict[str, Any] = {}


@TableOwnership.owned_by("kernel:tasks")
class TaskInstance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "kernel_task_instances"

    task_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[TaskPayload] = mapped_column(JsonBModel(TaskPayload, "1"), nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_seconds: Mapped[float] = mapped_column(nullable=False, default=60.0)
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result: Mapped[VersionedState | None] = mapped_column(
        JsonBModel(VersionedState, "1"), nullable=True
    )
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (Index("ix_kernel_task_due", "status", "next_run_at"),)


@TableOwnership.owned_by("kernel:tasks")
class CronState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persistent next-fire anchor per Cron key (database-scan scheduling)."""

    __tablename__ = "kernel_cron_state"

    cron_key: Mapped[str] = mapped_column(String(200), nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("cron_key", name="uq_kernel_cron_state_key"),)
