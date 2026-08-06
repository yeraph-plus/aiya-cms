"""Declarative issue module."""

from .definition import IssueContentType
from .wiring import register

__all__ = ["IssueContentType", "register"]
