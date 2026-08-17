"""Consumer-owned ports for content publication validation."""

from __future__ import annotations

import uuid
from typing import Protocol

from inc.capabilities.content.markdown import MarkdownDocument


class AssetReadiness(Protocol):
    """Minimal assets fact required by Markdown publication validation."""

    async def is_ready(self, asset_id: uuid.UUID) -> bool:
        """Whether an opaque asset reference is currently publishable."""

        ...


class ContentPublicationPolicy(Protocol):
    """Feature-bound validation that runs before content is publishable."""

    async def validate(self, *, document: MarkdownDocument) -> None:
        """Raise a safe validation error when the source cannot be published."""

        ...
