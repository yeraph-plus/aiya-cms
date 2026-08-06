"""Identity lifecycle events."""

from uuid import UUID

from pydantic import BaseModel

IDENTITY_EVENT_TYPES: tuple[str, ...] = ("user.banned", "user.unbanned", "user.deleted")


class UserStatusChangedPayload(BaseModel):
    user_id: UUID
    actor_id: UUID
