"""Declarative post module."""

from .definition import PostContentType
from .wiring import register

__all__ = ["PostContentType", "register"]
