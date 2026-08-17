"""Content capability: generic content entity, types, transitions,
scheduling, pinning and references.

Contract source: context/spec/capabilities/content.md.

Public surface for the composition root: type declarations, queries,
diagnostics and the scheduled-publish scanner/workflow wiring.
"""

from __future__ import annotations

from inc.capabilities.content.commands import CommandContext
from inc.capabilities.content.diagnostics import ContentDiagnostics
from inc.capabilities.content.markdown import MarkdownDocument
from inc.capabilities.content.ports import AssetReadiness, ContentPublicationPolicy
from inc.capabilities.content.publish import (
    ContentPublishScanner,
    ScheduledPublishActivity,
    register_publish_workflow,
)
from inc.capabilities.content.queries import ContentQueries
from inc.capabilities.content.types import (
    DEFAULT_TRANSITIONS,
    STANDARD_STATES,
    ContentTypeRegistry,
    ContentTypeSpec,
)

__all__ = [
    "CommandContext",
    "ContentDiagnostics",
    "ContentPublishScanner",
    "ContentQueries",
    "AssetReadiness",
    "ContentPublicationPolicy",
    "ContentTypeRegistry",
    "ContentTypeSpec",
    "MarkdownDocument",
    "DEFAULT_TRANSITIONS",
    "STANDARD_STATES",
    "ScheduledPublishActivity",
    "register_publish_workflow",
]
