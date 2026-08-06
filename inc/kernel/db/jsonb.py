"""JSONB column type backed by a Pydantic model (see context/spec/architecture.md)."""

from typing import Any

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator


class JsonBModel[ModelT: BaseModel](TypeDecorator[ModelT]):
    """Maps a Pydantic model instance to a PostgreSQL JSONB column.

    Bind dumps via ``model_dump(mode="json")``; result loads via
    ``model_validate``. Raw dicts are coerced through validation so malformed
    payloads fail loudly instead of writing junk to the column.
    """

    impl = JSONB
    cache_ok = True

    def __init__(self, model_type: type[ModelT], *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.model_type = model_type

    def process_bind_param(
        self,
        value: ModelT | dict[str, Any] | None,
        dialect: Any,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, self.model_type):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return self.model_type.model_validate(value).model_dump(mode="json")
        raise TypeError(f"expected {self.model_type.__name__} or dict, got {type(value).__name__}")

    def process_result_value(self, value: Any, dialect: Any) -> ModelT | None:
        if value is None:
            return None
        return self.model_type.model_validate(value)
