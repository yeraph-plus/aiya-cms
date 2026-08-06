"""Runtime setting domain events."""

from uuid import UUID

from pydantic import BaseModel, Field

SETTING_EVENT_TYPES: tuple[str, ...] = ("setting.updated",)


class SettingUpdatedPayload(BaseModel):
    key: str
    changed_fields: list[str] = Field(default_factory=list)
    actor_id: UUID
