"""Opaque content lookup port used by engagement commands."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ContentEngagementTarget:
    content_id: uuid.UUID
    type_name: str
    status: str
    published_at: datetime | None


class EngageableContentReader(Protocol):
    async def get(self, content_id: uuid.UUID) -> ContentEngagementTarget | None: ...
