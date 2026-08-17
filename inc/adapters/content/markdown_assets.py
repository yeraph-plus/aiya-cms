"""Content publication-policy adapter backed by an assets public Port."""

from __future__ import annotations

from inc.capabilities.content import AssetReadiness, MarkdownDocument
from inc.kernel.errors import ErrorCategory, KernelError


class ReadyMarkdownAssetsPolicy:
    """Require every opaque Markdown asset reference to be ready."""

    def __init__(self, readiness: AssetReadiness) -> None:
        self._readiness = readiness

    async def validate(self, *, document: MarkdownDocument) -> None:
        for asset_id in document.asset_ids:
            if not await self._readiness.is_ready(asset_id):
                raise KernelError(
                    code="content.markdown_asset_invalid",
                    category=ErrorCategory.VALIDATION,
                    message="markdown asset is not ready",
                )
