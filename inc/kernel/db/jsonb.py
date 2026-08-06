"""Pydantic-bound JSONB column type.

Contract source: context/spec/kernel/database.md §1, foundation.md §4.

Every persisted JSONB value is a self-describing envelope::

    {"schema_version": "1", "payload": {...}}

stored through a concrete Pydantic model. Unbounded ``dict[str, Any]``
columns are forbidden.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import TypeDecorator

PydanticModel = TypeVar("PydanticModel", bound=BaseModel)


class JsonBModel(TypeDecorator[dict[str, Any]]):
    """JSONB column bound to a Pydantic model and schema version."""

    cache_ok = True
    impl = postgresql.JSONB

    def __init__(self, model: type[PydanticModel], schema_version: str) -> None:
        super().__init__()
        if not schema_version:
            raise ValueError("JsonBModel requires a schema_version")
        self.model = model
        self.schema_version = schema_version

    def load_dialect_impl(self, dialect: Any) -> Any:
        # PostgreSQL stores JSONB; other dialects (SQLite tests) fall back to
        # the same JSON serialization shape.
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, self.model):
            raise TypeError(f"expected {self.model.__name__}, got {type(value).__name__}")
        return {
            "schema_version": self.schema_version,
            "payload": value.model_dump(mode="json"),
        }

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        payload = value.get("payload") if isinstance(value, dict) and "payload" in value else value
        return self.model.model_validate(payload)
