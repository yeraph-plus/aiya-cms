"""Content capability: generic content entity, types, transitions,
scheduling, pinning and references.

Contract source: context/spec/capabilities/content.md.

Content type declarations belong to features; this capability validates
and executes them. It imports neither taxonomy nor assets: dimensions are
managed by the taxonomy capability, and asset ids are opaque references.
"""

from __future__ import annotations

from inc.capabilities.content.types import (
    DEFAULT_TRANSITIONS,
    STANDARD_STATES,
    ContentTypeRegistry,
    ContentTypeSpec,
)

__all__ = [
    "DEFAULT_TRANSITIONS",
    "STANDARD_STATES",
    "ContentTypeRegistry",
    "ContentTypeSpec",
]
