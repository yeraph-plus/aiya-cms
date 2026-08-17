"""Scheduled publish: due scan, lease claim and publish workflow.

Contract source: context/spec/capabilities/content.md §6.

The scanner claims due scheduled rows with ``FOR UPDATE SKIP LOCKED`` on
PostgreSQL and with an atomic conditional update (lease columns) on other
dialects, then starts the ``content.publish_scheduled.v1`` workflow whose
business idempotency key is ``content_id:schedule_version``. Worker
restarts simply rescan the database; cancellation or rescheduling bumps
the schedule version so in-flight tasks become no-ops.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update

from inc.capabilities.content.models import Content
from inc.capabilities.content.ports import ContentPublicationPolicy
from inc.capabilities.content.publication import validate_publication
from inc.capabilities.content.types import ContentTypeRegistry
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError, RetryCategory
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock
from inc.kernel.workflow import (
    ActivityContext,
    ActivitySpec,
    RetryPolicy,
    WorkflowRegistry,
    WorkflowRunner,
    WorkflowSpec,
)

PUBLISH_WORKFLOW_KEY = "content.publish.scheduled.v1"
PUBLISH_ACTIVITY_KEY = "content.publish.scheduled.step.v1"


class ScheduledPublishActivity:
    """Idempotent publish step; runs inside the workflow runner UoW.

    The publish itself is an atomic conditional update
    (``status='scheduled' AND schedule_version=expected``), so a
    concurrently cancelled or rescheduled content loses the race and the
    step becomes a no-op. The workflow runner commits this UoW atomically
    with the step attempt, so the status change, the outbox event and the
    audit envelope commit together; replays are no-ops.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        outbox: OutboxWriter,
        types: ContentTypeRegistry,
        publication_policies: Mapping[str, ContentPublicationPolicy],
        actor_id: str | None = None,
    ) -> None:
        self._clock = clock
        self._outbox = outbox
        self._types = types
        self._publication_policies = publication_policies
        self._actor_id = actor_id

    async def __call__(
        self, uow: UnitOfWork, data: dict[str, Any], ctx: ActivityContext
    ) -> dict[str, Any]:
        workflow = data.get("workflow", {})
        content_id = workflow.get("content_id")
        expected_version = int(workflow.get("schedule_version", -1))
        if content_id is None:
            raise KernelError(
                code="content.publish_invalid_input",
                category=ErrorCategory.INTERNAL,
                message="publish workflow input is missing content_id",
            )
        row: Content | None = await uow.session.get(Content, uuid.UUID(str(content_id)))
        if row is None or row.status != "scheduled" or row.schedule_version != expected_version:
            return {"skipped": True, "reason": "not_scheduled_anymore"}
        await validate_publication(
            spec=self._types.require(row.type_name),
            body=row.body,
            excerpt=row.excerpt,
            policies=self._publication_policies,
        )
        now = self._clock.utc_now()
        result = await uow.session.execute(
            update(Content)
            .where(
                Content.id == row.id,
                Content.status == "scheduled",
                Content.schedule_version == expected_version,
            )
            .values(
                status="published",
                published_at=now,
                lease_owner=None,
                lease_expires_at=None,
                version=Content.version + 1,
                updated_at=now,
            )
        )
        if result.rowcount == 0:
            return {"skipped": True, "reason": "concurrent_state_change"}
        await uow.session.refresh(row)
        refreshed: Content = row
        await self._outbox.append(
            uow,
            EventEnvelope(
                event_id=uuid.uuid7(),
                event_key="content.published.v1",
                occurred_at=now,
                producer="content",
                aggregate_type="content",
                aggregate_id=str(refreshed.id),
                trace_id=ctx.trace_id,
                payload={
                    "content_id": str(refreshed.id),
                    "type_name": refreshed.type_name,
                    "slug": refreshed.slug,
                    "status": refreshed.status,
                    "version": refreshed.version,
                    "published_at": now.isoformat(),
                    "schedule_version": refreshed.schedule_version,
                },
            ),
        )
        await self._outbox.append(
            uow,
            EventEnvelope(
                event_id=uuid.uuid7(),
                event_key="audit.entry.recorded.v1",
                occurred_at=now,
                producer="content",
                aggregate_type="content",
                aggregate_id=str(refreshed.id),
                trace_id=ctx.trace_id,
                payload={
                    "action": "content.publish_scheduled",
                    "outcome": "success",
                    "occurred_at": now.isoformat(),
                    "actor_type": "system",
                    "actor_id": self._actor_id,
                    "target_type": refreshed.type_name,
                    "target_id": str(refreshed.id),
                    "trace_id": ctx.trace_id,
                    "details": {"schedule_version": refreshed.schedule_version},
                },
            ),
        )
        return {"skipped": False, "version": refreshed.version}


def build_publish_workflow_spec(activity: ScheduledPublishActivity) -> WorkflowSpec:
    return WorkflowSpec(
        key=PUBLISH_WORKFLOW_KEY,
        version="1",
        activities=(
            ActivitySpec(
                key=PUBLISH_ACTIVITY_KEY,
                timeout_seconds=30.0,
                retry=RetryPolicy(
                    max_attempts=3,
                    base_delay_seconds=1.0,
                    permanent_categories=frozenset(
                        {RetryCategory.PERMANENT, RetryCategory.CANCELLED}
                    ),
                ),
                handler=activity,
            ),
        ),
    )


class ContentPublishScanner:
    """Claims due scheduled content and starts publish workflows."""

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        clock: Clock,
        runner: WorkflowRunner,
        batch: int = 64,
        lease_owner: str = "content-publish-scanner",
        lease_seconds: int = 300,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._runner = runner
        self._batch = batch
        self._lease_owner = lease_owner
        self._lease_seconds = lease_seconds

    async def scan_once(self, *, now: Any | None = None) -> int:
        """Claim due rows once and start workflows; returns claims made."""

        current = now if now is not None else self._clock.utc_now()
        claimed: list[tuple[uuid.UUID, int]] = []
        async with self._uow_factory() as uow:
            due = and_(
                Content.status == "scheduled",
                Content.publish_at <= current,
                or_(
                    Content.lease_expires_at.is_(None),
                    Content.lease_expires_at < current,
                ),
            )
            statement = (
                select(Content.id, Content.schedule_version)
                .where(due)
                .order_by(Content.publish_at, Content.id)
                .limit(self._batch)
            )
            if uow.session.bind is not None and uow.session.bind.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
                rows = (await uow.session.execute(statement)).all()
                if rows:
                    expires = current + timedelta(seconds=self._lease_seconds)
                    await uow.session.execute(
                        update(Content)
                        .where(Content.id.in_([r[0] for r in rows]), due)
                        .values(lease_owner=self._lease_owner, lease_expires_at=expires)
                    )
                claimed = [(uuid.UUID(str(r[0])), int(r[1])) for r in rows]
            else:
                rows = (await uow.session.execute(statement)).all()
                if rows:
                    expires = current + timedelta(seconds=self._lease_seconds)
                    result = await uow.session.execute(
                        update(Content)
                        .where(Content.id.in_([r[0] for r in rows]), due)
                        .values(lease_owner=self._lease_owner, lease_expires_at=expires)
                    )
                    if result.rowcount:
                        refreshed = (
                            await uow.session.execute(
                                select(Content.id, Content.schedule_version).where(
                                    Content.id.in_([r[0] for r in rows]),
                                    Content.lease_owner == self._lease_owner,
                                )
                            )
                        ).all()
                        claimed = [(uuid.UUID(str(r[0])), int(r[1])) for r in refreshed]
            await uow.commit()

        for content_id, schedule_version in claimed:
            await self._runner.start(
                workflow_key=PUBLISH_WORKFLOW_KEY,
                idempotency_key=f"{content_id}:{schedule_version}",
                input_data={"content_id": str(content_id), "schedule_version": schedule_version},
                trace_id=f"publish:{content_id}",
            )
        return len(claimed)


def register_publish_workflow(
    registry: WorkflowRegistry, *, activity: ScheduledPublishActivity
) -> None:
    registry.register(build_publish_workflow_spec(activity))
