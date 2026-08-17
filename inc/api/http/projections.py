"""Small API-layer projections used by administrator workbenches.

Capability DTOs intentionally keep opaque subject/content identifiers.  The
admin UI may still need a readable label, so these projections are assembled
at the HTTP composition boundary without changing capability contracts.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AdminSubjectRefDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str
    subject_id: str
    username: str | None = None
    display_name: str | None = None
    avatar_asset_id: str | None = None


class AdminContentRefDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str
    target_id: str
    type_name: str | None = None
    title: str | None = None
    slug: str | None = None
    status: str | None = None
