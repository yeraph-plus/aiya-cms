"""Mail outbox repository queries."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select

from inc.kernel.db import Repository

from .models import MailOutbox, MailStatus


class MailOutboxRepository(Repository[MailOutbox]):
    model = MailOutbox

    async def get_for_update_or_none(self, mail_id: UUID) -> MailOutbox | None:
        return await super().get_for_update_or_none(mail_id)

    async def list_retryable(self, now: datetime) -> list[MailOutbox]:
        result = await self.session.scalars(
            select(MailOutbox)
            .where(
                or_(
                    MailOutbox.status == MailStatus.FAILED.value,
                    MailOutbox.status == MailStatus.SENDING.value,
                ),
                MailOutbox.attempts < 5,
                (MailOutbox.next_attempt_at.is_(None) | (MailOutbox.next_attempt_at <= now)),
            )
            .order_by(MailOutbox.created_at)
            .with_for_update(skip_locked=True)
        )
        return list(result.all())

    async def claim_for_attempt(
        self, mail_id: UUID, now: datetime, lease: datetime
    ) -> tuple[MailOutbox, int] | None:
        row = await self.get_for_update_or_none(mail_id)
        if row is None or row.status in {MailStatus.SENT.value, MailStatus.DEAD.value}:
            return None
        if row.status == MailStatus.SENDING.value and row.next_attempt_at is not None:
            if row.next_attempt_at > now:
                return None
        elif row.next_attempt_at is not None and row.next_attempt_at > now:
            return None
        row.attempts += 1
        row.status = MailStatus.SENDING.value
        row.next_attempt_at = lease
        return row, row.attempts
