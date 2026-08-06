"""Content kernel unit of work."""

from inc.kernel.db import AbstractUnitOfWork

from .repositories import ContentRepository


class ContentUnitOfWork(AbstractUnitOfWork):
    @property
    def contents(self) -> ContentRepository:
        return ContentRepository(self.session)
