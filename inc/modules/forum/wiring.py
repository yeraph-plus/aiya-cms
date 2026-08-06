"""Explicit forum declaration registration."""

from inc.kernel.content import ContentTypeRegistry

from .definition import ForumContentType


def register(registry: ContentTypeRegistry) -> None:
    registry.register(ForumContentType)
