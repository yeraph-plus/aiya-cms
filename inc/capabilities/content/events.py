"""Content events.

Contract source: context/spec/capabilities/content.md §9.

Events carry only stable base fields and minimal change summaries; full
body/data is fetched through queries. Keys are the stable cross-capability
contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: str
    type_name: str
    slug: str
    status: str
    version: int


class ContentCreatedPayload(_Base):
    title: str


class ContentUpdatedPayload(_Base):
    changed: tuple[str, ...] = ()


class ContentSubmittedPayload(_Base):
    pass


class ContentScheduledPayload(_Base):
    publish_at: datetime
    schedule_version: int


class ContentScheduleCancelledPayload(_Base):
    schedule_version: int


class ContentPublishedPayload(_Base):
    published_at: datetime
    schedule_version: int


class ContentArchivedPayload(_Base):
    pass


class ContentPinChangedPayload(_Base):
    is_pinned: bool
    pin_rank: int


CONTENT_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "content.created.v1": ContentCreatedPayload,
    "content.updated.v1": ContentUpdatedPayload,
    "content.submitted.v1": ContentSubmittedPayload,
    "content.scheduled.v1": ContentScheduledPayload,
    "content.schedule_cancelled.v1": ContentScheduleCancelledPayload,
    "content.published.v1": ContentPublishedPayload,
    "content.archived.v1": ContentArchivedPayload,
    "content.pin_changed.v1": ContentPinChangedPayload,
}

for _key in CONTENT_EVENT_SCHEMAS:
    validate_error_code(_key)


def _payload(key: str, **values: Any) -> dict[str, Any]:
    return CONTENT_EVENT_SCHEMAS[key].model_validate(values).model_dump(mode="json")
