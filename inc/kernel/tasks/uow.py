"""Task persistence transaction boundary."""

from inc.kernel.db import AbstractUnitOfWork

from .repositories import TaskRepository


class TaskUnitOfWork(AbstractUnitOfWork):
    @property
    def tasks(self) -> TaskRepository:
        return TaskRepository(self.session)
