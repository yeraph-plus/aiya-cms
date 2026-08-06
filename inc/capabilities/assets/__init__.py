"""Assets capability: external object storage references.

Contract source: context/spec/capabilities/assets.md.

Public surface for the composition root: command context, workflow
registration, queries and diagnostics.
"""

from __future__ import annotations

from inc.capabilities.assets.commands import CommandContext, register_asset_workflows
from inc.capabilities.assets.diagnostics import AssetDiagnostics
from inc.capabilities.assets.queries import AssetQueries

__all__ = [
    "AssetDiagnostics",
    "AssetQueries",
    "CommandContext",
    "register_asset_workflows",
]
