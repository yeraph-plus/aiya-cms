"""Declarative runtime-setting definitions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, cast

from pydantic import BaseModel, ConfigDict, Field, create_model

type SettingValidator[T] = Callable[[T], T]


@dataclass(frozen=True, slots=True)
class SettingField[T]:
    """One typed, documented and optionally public setting value."""

    slug: str
    title: str
    description: str
    value_type: Any
    default: T
    is_public: bool = False
    validator: SettingValidator[T] | None = None
    constraints: dict[str, Any] = field(default_factory=dict)


class SettingGroup:
    """Abstract base class for readable, code-owned setting declarations."""

    slug: ClassVar[str]
    group_title: ClassVar[str] = ""
    group_description: ClassVar[str] = ""
    order: ClassVar[int] = 100
    _value_model: ClassVar[type[BaseModel] | None] = None

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls._value_model = None

    @classmethod
    def fields(cls) -> tuple[SettingField[Any], ...]:
        result: list[SettingField[Any]] = []
        for value in cls.__dict__.values():
            if isinstance(value, SettingField):
                result.append(value)
        return tuple(result)

    @classmethod
    def value_model(cls) -> type[BaseModel]:
        if cls._value_model is not None:
            return cls._value_model
        definitions = cls.fields()
        field_names = [field.slug for field in definitions]
        if len(field_names) != len(set(field_names)):
            raise ValueError(f"duplicate setting field slug in {cls.__name__}")
        model_fields: dict[str, tuple[Any, Any]] = {}
        for definition in definitions:
            schema_extra = {
                "slug": definition.slug,
                "is_public": definition.is_public,
                **definition.constraints,
            }
            model_fields[definition.slug] = (
                definition.value_type,
                Field(
                    default=definition.default,
                    title=definition.title,
                    description=definition.description,
                    json_schema_extra=schema_extra,
                ),
            )
        cls._value_model = create_model(
            f"{cls.__name__}Value",
            __config__=ConfigDict(extra="forbid"),
            **cast(dict[str, Any], model_fields),
        )
        return cls._value_model

    @classmethod
    def validate_group(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Hook for cross-field validation; subclasses may return normalized values."""

        return values
