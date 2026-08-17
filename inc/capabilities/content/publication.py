"""Shared content publication validation for commands and scheduled workflows."""

from __future__ import annotations

from collections.abc import Mapping

from inc.capabilities.content.markdown import validate_markdown
from inc.capabilities.content.ports import ContentPublicationPolicy
from inc.capabilities.content.types import ContentTypeSpec
from inc.kernel.errors import ErrorCategory, KernelError


def _validation(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


async def validate_publication(
    *,
    spec: ContentTypeSpec,
    body: str | None,
    excerpt: str | None,
    policies: Mapping[str, ContentPublicationPolicy],
) -> None:
    """Require publishable source facts and invoke the feature-bound policy."""

    document = validate_markdown(spec, body)
    if excerpt is None or not excerpt.strip():
        raise _validation("content.excerpt_required", "published content requires an excerpt")
    if document.source is None or not document.source.strip():
        raise _validation("content.markdown_invalid", "published content requires markdown body")
    if not spec.requires_ready_markdown_assets:
        return
    policy = policies.get(spec.publication_policy_key or "")
    if policy is None:
        raise _validation(
            "content.markdown_asset_invalid", "markdown publication policy is unavailable"
        )
    await policy.validate(document=document)
