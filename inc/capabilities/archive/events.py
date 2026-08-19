"""Archive event payload schemas with no provider secrets or locators."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class ArchiveItemEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    item_key: str
    provider_key: str
    state: str
    version: int


class ArchiveGrantEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: str
    status: str
    manifest_version: str
    manifest_digest: str


ARCHIVE_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "archive.item_registered.v1": ArchiveItemEventPayload,
    "archive.item_activated.v1": ArchiveItemEventPayload,
    "archive.item_unavailable.v1": ArchiveItemEventPayload,
    "archive.item_retired.v1": ArchiveItemEventPayload,
    "archive.grant_issued.v1": ArchiveGrantEventPayload,
    "archive.grant_activated.v1": ArchiveGrantEventPayload,
    "archive.grant_expired.v1": ArchiveGrantEventPayload,
    "archive.grant_revoked.v1": ArchiveGrantEventPayload,
}

for _key in ARCHIVE_EVENT_SCHEMAS:
    validate_error_code(_key)
