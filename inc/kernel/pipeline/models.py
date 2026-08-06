"""Pipeline keys, contexts and definitions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from inc.kernel.security import Principal

PipelineKind = Literal["read", "write"]
PipelinePhase = Literal["before", "after"]


class PipelineKey(str):
    """Stable value object used for explicit pipeline registration."""

    def __new__(cls, value: str) -> PipelineKey:
        if not isinstance(value, str) or not value or value.strip() != value:
            raise ValueError(
                "pipeline key must be a non-empty string without surrounding whitespace"
            )
        return str.__new__(cls, value)


class RequestMeta(BaseModel):
    """Request metadata available to pipeline steps and audit adapters."""

    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


class ExtensionBag(dict[str, BaseModel]):
    """Dictionary that keeps extension values as Pydantic models at runtime."""

    def __setitem__(self, key: str, value: BaseModel) -> None:
        if not isinstance(value, BaseModel):
            raise TypeError("pipeline extensions must be Pydantic models")
        super().__setitem__(key, value)

    def update(self, values: Any = (), /, **kwargs: BaseModel) -> None:
        items = values.items() if hasattr(values, "items") else values
        for key, value in items:
            self[key] = value
        for key, value in kwargs.items():
            self[key] = value


class StepContext(BaseModel):
    """Typed data envelope shared by every step in one pipeline run."""

    model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)

    principal: Principal
    payload: BaseModel
    extensions: ExtensionBag = Field(default_factory=ExtensionBag)
    request: RequestMeta = Field(default_factory=RequestMeta)
    # The executor installs the active UoW for write steps. It is excluded from
    # DTO serialization and intentionally has no public persistence API.
    uow: Any | None = Field(default=None, exclude=True, repr=False)

    @field_validator("extensions", mode="before")
    @classmethod
    def validate_extensions(cls, value: object) -> object:
        if isinstance(value, ExtensionBag):
            return value
        if not isinstance(value, dict) or any(
            not isinstance(extension, BaseModel) for extension in value.values()
        ):
            raise ValueError("pipeline extensions must be Pydantic models")
        return ExtensionBag(value)

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, value: object) -> object:
        if not isinstance(value, BaseModel):
            raise ValueError("pipeline payload must be a Pydantic model")
        return value


Step = Callable[[StepContext], Awaitable[None]]


@dataclass
class PipelineDef:
    """A registered pipeline and its explicitly attached steps."""

    key: PipelineKey
    owner: str
    kind: PipelineKind
    core: Step
    before: list[Step] = field(default_factory=list)
    after: list[Step] = field(default_factory=list)
    uow_factory: Callable[[], Any] | None = None
