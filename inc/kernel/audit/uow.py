"""Audit transaction boundary."""

from inc.kernel.db import AbstractUnitOfWork

from .repositories import AuditRepository


class AuditUnitOfWork(AbstractUnitOfWork):
    @property
    def logs(self) -> AuditRepository:
        return AuditRepository(self.session)
