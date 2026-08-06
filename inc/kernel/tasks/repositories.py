"""Task-instance repository queries."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select

from inc.kernel.db import Page, Repository

from .models import TaskInstance, TaskState


class TaskRepository(Repository[TaskInstance]):
    model = TaskInstance

    async def list_filtered(
        self,
        *,
        task_type: str | None = None,
        state: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[TaskInstance]:
        filters = []
        if task_type is not None:
            filters.append(TaskInstance.task_type == task_type)
        if state is not None:
            filters.append(TaskInstance.state == state)
        if created_from is not None:
            filters.append(TaskInstance.created_at >= created_from)
        if created_to is not None:
            filters.append(TaskInstance.created_at <= created_to)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(TaskInstance).where(*filters)
            )
            or 0
        )
        rows = await self.session.scalars(
            select(TaskInstance)
            .where(*filters)
            .order_by(TaskInstance.created_at.desc(), TaskInstance.id.desc())
            .limit(size)
            .offset((page - 1) * size)
        )
        return Page(items=list(rows.all()), total=total, page=page, size=size)

    async def get_for_update_or_none(self, task_id: UUID) -> TaskInstance | None:
        return await super().get_for_update_or_none(task_id)

    async def get_active_by_idempotency(
        self, task_type: str, idempotency_key: str
    ) -> TaskInstance | None:
        result = await self.session.scalars(
            select(TaskInstance)
            .where(
                TaskInstance.task_type == task_type,
                TaskInstance.idempotency_key == idempotency_key,
                TaskInstance.state.not_in(
                    [TaskState.SUCCEEDED.value, TaskState.FAILED.value, TaskState.CANCELLED.value]
                ),
            )
            .with_for_update()
        )
        return result.first()

    async def list_orphans(self, now: datetime) -> list[TaskInstance]:
        result = await self.session.scalars(
            select(TaskInstance)
            .where(
                TaskInstance.state == TaskState.RUNNING.value,
                TaskInstance.timeout_at.is_not(None),
                TaskInstance.timeout_at <= now,
            )
            .with_for_update()
        )
        return list(result.all())
