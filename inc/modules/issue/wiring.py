"""Explicit issue declaration registration."""

from inc.kernel.content import ContentTypeRegistry

from .definition import IssueContentType


def register(registry: ContentTypeRegistry) -> None:
    registry.register(IssueContentType)
