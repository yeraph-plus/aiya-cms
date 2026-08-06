"""Settings events.

Contract source: context/spec/capabilities/settings.md §6.

The update event carries the group key, new version and a safe change
summary; sensitive field values and diffs never enter the payload.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class GroupUpdatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_key: str
    version: int
    changed_fields: tuple[str, ...] = ()


SETTINGS_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "settings.group_updated.v1": GroupUpdatedPayload,
}

for _key in SETTINGS_EVENT_SCHEMAS:
    validate_error_code(_key)
