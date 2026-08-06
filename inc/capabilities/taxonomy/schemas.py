"""Taxonomy DTOs and command inputs.

Contract source: context/spec/capabilities/taxonomy.md §4/§5.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DimensionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_key: str
    version: str
    display_name: str
    selection_mode: str
    min_items: int
    max_items: int
    public_visible: bool


class TermDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dimension_key: str
    name: str
    slug: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str


class CreateTermInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateTermInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class AssignTermsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str
    target_id: uuid.UUID
    term_ids: list[uuid.UUID] = Field(default_factory=list)
