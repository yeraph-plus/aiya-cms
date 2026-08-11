"""Idempotent projection of content lifecycle facts into engagement stats."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from inc.capabilities.engagement.models import ContentEngagementStats
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.events import EventEnvelope, InboxGuard
from inc.kernel.time import Clock


class ContentEngagementProjection:
    key = "engagement.content_projection.v1"

    def __init__(self, *, uow_factory: UoWFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def handle(self, envelope: EventEnvelope, uow: UnitOfWork) -> None:
        async def work() -> None:
            payload = envelope.payload
            content_id = uuid.UUID(str(payload["content_id"]))
            status = str(payload.get("status", "draft"))
            event_version = int(payload.get("version", 0))
            row = (
                (
                    await uow.session.execute(
                        select(ContentEngagementStats).where(
                            ContentEngagementStats.content_id == content_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            published_at: datetime | None = None
            raw_published_at = payload.get("published_at")
            if isinstance(raw_published_at, datetime):
                published_at = raw_published_at
            elif isinstance(raw_published_at, str):
                published_at = datetime.fromisoformat(raw_published_at)
            if row is None:
                row = ContentEngagementStats(
                    content_id=content_id,
                    type_name=str(payload.get("type_name", "unknown")),
                    content_status=status,
                    published_at=published_at,
                    projected_at=self._clock.utc_now(),
                    projection_version=max(event_version, 1),
                )
                uow.session.add(row)
            else:
                # A replayed or delayed lifecycle event must never roll a
                # projection back.  Purge is a terminal tombstone even when
                # it shares the final content version.
                if row.content_status == "purged" and status != "purged":
                    return
                if event_version < int(row.projection_version):
                    return
                row.projection_version = max(int(row.projection_version), event_version)
                row.type_name = str(payload.get("type_name", row.type_name))
                row.content_status = status
                if status == "purged":
                    row.published_at = None
                elif published_at is not None:
                    row.published_at = published_at
                row.projected_at = self._clock.utc_now()

        await InboxGuard.process(
            uow,
            handler_key=self.key,
            event_id=envelope.event_id,
            work=work,
            processed_at=self._clock.utc_now(),
        )
