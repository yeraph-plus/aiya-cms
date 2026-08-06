"""Internal audit events and their typed payload."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

AUDIT_EVENT_TYPES: tuple[str, ...] = ("audit.recorded",)


class AuditRecordPayload(BaseModel):
    actor_id: UUID | None
    actor_type: str
    action: str
    target_type: str | None = None
    target_id: UUID | None = None
    context: dict[str, object] | None = None
    ip: str | None = None
    occurred_at: datetime
