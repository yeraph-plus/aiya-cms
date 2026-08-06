"""Interaction DTOs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class InteractionRead(BaseModel):
    id: UUID
    user_id: UUID
    target_type: str
    target_id: UUID
    kind: Literal["like", "rating"]
    numeric_value: int | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class InteractionQuery(BaseModel):
    kind: Literal["like", "rating"] | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class RatingWrite(BaseModel):
    score: int = Field(ge=1, le=5)


class InteractionChangedPayload(BaseModel):
    user_id: UUID
    target_type: str
    target_id: UUID
    kind: Literal["like", "rating"]
    numeric_value: int | None = None
    deleted: bool = False
    existed: bool = False
    previous_value: int | None = None
