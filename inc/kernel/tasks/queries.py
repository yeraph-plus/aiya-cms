"""Read-only, secret-free view of kernel execution records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, String, cast, func, literal, select, union_all

from inc.kernel.db import Page, UoWFactory
from inc.kernel.events.models import InboxReceipt, OutboxMessage
from inc.kernel.tasks.models import TaskInstance

ExecutionKind = Literal["outbox", "inbox", "task"]


class ExecutionEntryDTO(BaseModel):
    """Minimal operational record; payloads and free-form results are omitted."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: ExecutionKind
    key: str
    status: str
    occurred_at: datetime
    updated_at: datetime
    attempts: int | None = None
    error_category: str | None = None


class ExecutionLogQueries:
    """Paginated read model over outbox, inbox and task terminal history."""

    def __init__(self, *, uow_factory: UoWFactory) -> None:
        self._uow_factory = uow_factory

    async def list_entries(
        self,
        *,
        page: int,
        size: int,
        kind: ExecutionKind | None = None,
        key: str | None = None,
        status: str | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
    ) -> Page[ExecutionEntryDTO]:
        if page < 1:
            raise ValueError("page must be >= 1")
        if not 1 <= size <= 200:
            raise ValueError("size must be between 1 and 200")

        outbox = select(
            cast(OutboxMessage.id, String).label("id"),
            literal("outbox").label("kind"),
            OutboxMessage.event_key.label("key"),
            OutboxMessage.status.label("status"),
            OutboxMessage.created_at.label("occurred_at"),
            OutboxMessage.updated_at.label("updated_at"),
            OutboxMessage.attempts.label("attempts"),
            OutboxMessage.last_error_category.label("error_category"),
        )
        inbox = select(
            cast(InboxReceipt.id, String).label("id"),
            literal("inbox").label("kind"),
            InboxReceipt.handler_key.label("key"),
            literal("processed").label("status"),
            InboxReceipt.processed_at.label("occurred_at"),
            InboxReceipt.updated_at.label("updated_at"),
            literal(None).cast(Integer).label("attempts"),
            literal(None).cast(String).label("error_category"),
        )
        tasks = select(
            cast(TaskInstance.id, String).label("id"),
            literal("task").label("kind"),
            TaskInstance.task_key.label("key"),
            TaskInstance.status.label("status"),
            TaskInstance.created_at.label("occurred_at"),
            TaskInstance.updated_at.label("updated_at"),
            TaskInstance.attempt.label("attempts"),
            TaskInstance.error_category.label("error_category"),
        )

        entries = union_all(outbox, inbox, tasks).subquery("execution_entries")
        statement = select(entries)
        if kind is not None:
            statement = statement.where(entries.c.kind == kind)
        if key is not None:
            statement = statement.where(entries.c.key == key)
        if status is not None:
            statement = statement.where(entries.c.status == status)
        if occurred_after is not None:
            statement = statement.where(entries.c.occurred_at >= occurred_after)
        if occurred_before is not None:
            statement = statement.where(entries.c.occurred_at <= occurred_before)

        count = await self._count_and_page(statement, entries, page=page, size=size)
        return count

    async def _count_and_page(  # type: ignore[return]
        self, statement: Any, entries: Any, *, page: int, size: int
    ) -> Page[ExecutionEntryDTO]:
        async with self._uow_factory() as uow:
            count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
            total = int((await uow.session.execute(count_statement)).scalar_one())
            rows = (
                await uow.session.execute(
                    statement.order_by(entries.c.occurred_at.desc(), entries.c.id)
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).mappings()
            items = [
                ExecutionEntryDTO(
                    id=str(row["id"]),
                    kind=row["kind"],
                    key=row["key"],
                    status=row["status"],
                    occurred_at=row["occurred_at"],
                    updated_at=row["updated_at"],
                    attempts=row["attempts"],
                    error_category=row["error_category"],
                )
                for row in rows
            ]
            return Page(items=items, total=total, page=page, size=size)
