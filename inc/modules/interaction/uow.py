"""Interaction transaction boundary."""

from inc.kernel.db import AbstractUnitOfWork

from .repositories import InteractionRepository


class InteractionUnitOfWork(AbstractUnitOfWork):
    @property
    def interactions(self) -> InteractionRepository:
        return InteractionRepository(self.session)
