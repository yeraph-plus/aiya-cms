"""Settings capability: structured, registered configuration groups.

Contract source: context/spec/capabilities/settings.md.

Passive host: group declarations (fields + metadata) are provided by
downstream (features, composition root); settings persists, validates,
gates by permission, publishes events and serves public reads. It never
declares groups of its own.
"""

from __future__ import annotations

from inc.capabilities.settings.groups import (
    SettingFieldMetadata,
    SettingFieldSpec,
    SettingGroupRegistry,
    SettingGroupSpec,
    SettingOption,
)
from inc.capabilities.settings.service import (
    CommandContext,
    ResetSettingGroup,
    SettingsQueries,
    UpdateSettingGroup,
    redact_sensitive_group,
)

__all__ = [
    "CommandContext",
    "ResetSettingGroup",
    "SettingFieldMetadata",
    "SettingFieldSpec",
    "SettingGroupRegistry",
    "SettingGroupSpec",
    "SettingOption",
    "SettingsQueries",
    "UpdateSettingGroup",
    "redact_sensitive_group",
]
