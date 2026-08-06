"""Explicit post declaration registration."""

from inc.kernel.content import ContentTypeRegistry

from .definition import PostContentType


def register(registry: ContentTypeRegistry) -> None:
    registry.register(PostContentType)
