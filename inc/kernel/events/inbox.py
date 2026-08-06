"""Inbox deduplication guard.

Contract source: context/spec/kernel/events.md §4.

Handlers deduplicate on ``(handler_key, event_id)``; the receipt and the
handler's business writes commit in the same UoW. At-least-once delivery
therefore never double-applies, and a handler that fails mid-way leaves no
success receipt behind.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select

from inc.kernel.db import UnitOfWork
from inc.kernel.events.models import InboxReceipt


class InboxGuard:
    """Idempotency guard for one handler/event pair."""

    @staticmethod
    async def already_processed(
        uow: UnitOfWork,
        *,
        handler_key: str,
        event_id: Any,
    ) -> bool:
        result = await uow.session.execute(
            select(InboxReceipt.id).where(
                InboxReceipt.handler_key == handler_key,
                InboxReceipt.event_id == event_id,
            )
        )
        return result.first() is not None

    @staticmethod
    async def mark_processed(
        uow: UnitOfWork,
        *,
        handler_key: str,
        event_id: Any,
        processed_at: datetime,
    ) -> None:
        uow.session.add(
            InboxReceipt(
                handler_key=handler_key,
                event_id=event_id,
                processed_at=processed_at,
            )
        )

    @classmethod
    async def process(
        cls,
        uow: UnitOfWork,
        *,
        handler_key: str,
        event_id: Any,
        work: Callable[[], Awaitable[None]],
        processed_at: datetime,
    ) -> bool:
        """Run *work* exactly once; returns True when actually executed."""

        if await cls.already_processed(uow, handler_key=handler_key, event_id=event_id):
            return False
        await work()
        await cls.mark_processed(
            uow, handler_key=handler_key, event_id=event_id, processed_at=processed_at
        )
        return True
