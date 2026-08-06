"""Task state, persistence model and public DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, Index, String, Uuid, and_, column
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TimestampMixin, new_uuid7


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


class TaskPayload(BaseModel):
    """Base payload model used by the dynamic JSONB task column."""

    model_config = ConfigDict(extra="allow")


class TaskResult(BaseModel):
    """Base result model used by the dynamic JSONB task column."""

    model_config = ConfigDict(extra="allow")


class TaskError(BaseModel):
    code: str
    message: str
    rollback_error: str | None = None


class TaskInstance(Base, TimestampMixin):
    __tablename__ = "task_instances"
    __table_args__ = (
        Index("ix_task_instances_type_state", "task_type", "state"),
        Index(
            "uq_task_instances_idem",
            "idempotency_key",
            unique=True,
            postgresql_where=and_(
                column("idempotency_key").is_not(None),
                column("state").not_in(
                    [TaskState.SUCCEEDED.value, TaskState.FAILED.value, TaskState.CANCELLED.value]
                ),
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=TaskState.PENDING.value)
    payload: Mapped[TaskPayload] = mapped_column(JsonBModel(TaskPayload), nullable=False)
    result: Mapped[TaskResult | None] = mapped_column(JsonBModel(TaskResult), nullable=True)
    error: Mapped[TaskError | None] = mapped_column(JsonBModel(TaskError), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskInstanceRead(BaseModel):
    """Public task-instance DTO; payload/result are always Pydantic models."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_type: str
    state: TaskState
    payload: BaseModel
    result: BaseModel | None = None
    error: TaskError | None = None
    idempotency_key: str | None = None
    timeout_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TaskQuery(BaseModel):
    task_type: str | None = Field(default=None, max_length=64)
    state: TaskState | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


def model_dump_json(value: BaseModel | None) -> dict[str, Any] | None:
    """Serialize a task JSONB model through the single JSONB boundary."""

    return None if value is None else value.model_dump(mode="json")
