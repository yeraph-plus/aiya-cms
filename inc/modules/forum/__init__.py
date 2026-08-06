"""Declarative forum module."""

from .definition import ForumContentType
from .wiring import register

__all__ = ["ForumContentType", "register"]
