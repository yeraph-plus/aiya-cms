"""Mail transaction boundary."""

from inc.kernel.db import AbstractUnitOfWork

from .repositories import MailOutboxRepository


class MailUnitOfWork(AbstractUnitOfWork):
    @property
    def outbox(self) -> MailOutboxRepository:
        return MailOutboxRepository(self.session)
