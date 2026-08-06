"""Kernel taxonomy unit of work."""

from inc.kernel.db import AbstractUnitOfWork

from .repositories import TermRelationshipRepository, TermRepository


class TaxonomyUnitOfWork(AbstractUnitOfWork):
    @property
    def terms(self) -> TermRepository:
        return TermRepository(self.session)

    @property
    def relationships(self) -> TermRelationshipRepository:
        return TermRelationshipRepository(self.session)
