"""Settings DTOs and command inputs.

Contract source: context/spec/capabilities/settings.md §4/§5.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class SettingGroupDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_key: str
    schema_version: str
    version: int
    values: dict[str, Any]
    updated_by: str | None = None
    updated_at: datetime | None = None


class PublicSettingsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any]


class UpdateSettingGroupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = None
    values: dict[str, Any]
