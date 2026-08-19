"""Assets capability: external object storage references.

Contract source: context/spec/capabilities/assets.md.

Public surface for the composition root: command context, workflow
registration, queries and diagnostics.
"""

from __future__ import annotations

from inc.capabilities.assets.commands import (
    CommandContext,
    CreateUploadIntent,
    DeleteAsset,
    FinalizeAsset,
    FinalizeContentImage,
    NormalizeContentImage,
    NormalizedImageResult,
    register_asset_workflows,
)
from inc.capabilities.assets.diagnostics import AssetDiagnostics
from inc.capabilities.assets.queries import AssetQueries
from inc.capabilities.assets.schemas import (
    AssetRefDTO,
    CreateUploadIntentInput,
    CreateUploadIntentResult,
    FinalizeResultDTO,
    ResolvedAssetUrlDTO,
)

__all__ = [
    "AssetDiagnostics",
    "AssetQueries",
    "AssetRefDTO",
    "CommandContext",
    "CreateUploadIntent",
    "CreateUploadIntentInput",
    "CreateUploadIntentResult",
    "DeleteAsset",
    "FinalizeAsset",
    "FinalizeResultDTO",
    "FinalizeContentImage",
    "NormalizeContentImage",
    "NormalizedImageResult",
    "ResolvedAssetUrlDTO",
    "register_asset_workflows",
]
