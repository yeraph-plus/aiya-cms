"""Workflow persistence models (kernel-owned tables).

Contract source: context/spec/kernel/workflow-tasks.md §2.

Every persisted workflow value is a versioned Pydantic payload. Status
strings are stable: ``pending``/``completed``/``failed``/``cancelled``/
``waiting`` for instances, ``executed``/``failed`` for step attempts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin


class VersionedState(BaseModel):
    """Versioned workflow payload; business schemas are declared per spec."""

    schema_version: str
    data: dict[str, Any] = {}


@TableOwnership.owned_by("kernel:workflow")
class WorkflowInstance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "kernel_workflow_instances"

    workflow_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    workflow_version: Mapped[str] = mapped_column(String(32), nullable=False)
    business_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    input: Mapped[VersionedState] = mapped_column(JsonBModel(VersionedState, "1"), nullable=False)
    state: Mapped[VersionedState] = mapped_column(
        JsonBModel(VersionedState, "1"),
        nullable=False,
        default=lambda: VersionedState(schema_version="1"),
    )
    current_step: Mapped[str | None] = mapped_column(String(200), nullable=True)
    step_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[VersionedState | None] = mapped_column(
        JsonBModel(VersionedState, "1"), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "workflow_key",
            "business_idempotency_key",
            name="uq_kernel_workflow_idempotency",
        ),
        Index("ix_kernel_workflow_due", "status", "wake_at"),
    )


@TableOwnership.owned_by("kernel:workflow")
class WorkflowStepAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "kernel_workflow_step_attempts"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("kernel_workflow_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="executed")
    input: Mapped[VersionedState] = mapped_column(JsonBModel(VersionedState, "1"), nullable=False)
    result: Mapped[VersionedState | None] = mapped_column(
        JsonBModel(VersionedState, "1"), nullable=True
    )
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "step_key",
            "attempt",
            name="uq_kernel_workflow_step_attempt",
        ),
    )


@TableOwnership.owned_by("kernel:workflow")
class WorkflowSignal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "kernel_workflow_signals"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("kernel_workflow_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signal_key: Mapped[str] = mapped_column(String(200), nullable=False)
    signal_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    payload: Mapped[VersionedState] = mapped_column(JsonBModel(VersionedState, "1"), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "signal_key",
            "signal_id",
            name="uq_kernel_workflow_signal",
        ),
        Index(
            "ix_kernel_workflow_signals_undelivered", "workflow_id", "signal_key", "delivered_at"
        ),
    )
