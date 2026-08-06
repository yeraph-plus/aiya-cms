"""Settings capability: structured, registered configuration groups.

Contract source: context/spec/capabilities/settings.md.

Public surface for the composition root: group registry, the seo group
declaration, queries, commands and the command context.
"""

from __future__ import annotations

from inc.capabilities.settings.groups import SettingGroupRegistry
from inc.capabilities.settings.seo import build_seo_group_spec
from inc.capabilities.settings.service import (
    CommandContext,
    ResetSettingGroup,
    SettingsQueries,
    UpdateSettingGroup,
)

__all__ = [
    "CommandContext",
    "ResetSettingGroup",
    "SettingGroupRegistry",
    "SettingsQueries",
    "UpdateSettingGroup",
    "build_seo_group_spec",
]
