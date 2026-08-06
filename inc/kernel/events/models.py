"""Pydantic event envelope."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    """An in-process domain event with a typed Pydantic payload."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str = Field(pattern=r"^[a-z0-9]+(?:\.[a-z0-9_]+)+$")
    payload: BaseModel
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor_id: UUID | None = None
