"""Runtime settings persistence models and HTTP DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel
from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel


class SettingOverrides(RootModel[dict[str, Any]]):
    """Sparse, user-owned values stored in the settings JSONB column."""


class SettingPatch(BaseModel):
    """User values and explicit resets accepted by the administrator API."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(default_factory=dict)
    unset: list[str] = Field(default_factory=list)


class SettingFieldDefinitionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    slug: str
    title: str
    description: str
    type: str
    is_public: bool
    default: Any
    value: Any
    is_overridden: bool
    json_schema: dict[str, Any] = Field(
        default_factory=dict, alias="schema", serialization_alias="schema"
    )


class SettingGroupRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    slug: str
    title: str
    description: str
    order: int
    fields: list[SettingFieldDefinitionRead]


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[SettingOverrides] = mapped_column(JsonBModel(SettingOverrides), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()", onupdate="now()"
    )
