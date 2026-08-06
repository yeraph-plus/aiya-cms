"""Registered task lifecycle events."""

from uuid import UUID

from pydantic import BaseModel

TASK_EVENT_TYPES = (
    "task.started",
    "task.succeeded",
    "task.failed",
    "task.cancelled",
)


class TaskEventPayload(BaseModel):
    task_id: UUID
    task_type: str
    reason: str | None = None
