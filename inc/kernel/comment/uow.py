"""Comment kernel unit of work."""

from inc.kernel.db import AbstractUnitOfWork

from .repositories import CommentRepository


class CommentUnitOfWork(AbstractUnitOfWork):
    @property
    def comments(self) -> CommentRepository:
        return CommentRepository(self.session)
