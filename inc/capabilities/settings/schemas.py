"""Settings DTOs and command inputs.

Contract source: context/spec/capabilities/settings.md §4/§5.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from inc.capabilities.settings.groups import SettingFieldType


class SettingFieldDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    type: SettingFieldType
    type_sub: str | None = None
    default: Any
    metadata: dict[str, Any]
    public: bool
    sensitive: bool


class SettingGroupDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_key: str
    schema_version: str
    version: int
    fields: tuple[SettingFieldDTO, ...]
    values: dict[str, Any]
    sensitive_configured: dict[str, bool] = Field(default_factory=dict)
    updated_by: str | None = None
    updated_at: datetime | None = None


class PublicSettingsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, dict[str, Any]]


class UpdateSettingGroupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    values: dict[str, Any]
    clear_sensitive_fields: tuple[str, ...] | None = None
