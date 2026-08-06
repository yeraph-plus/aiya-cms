"""Identity unit of work: one transaction boundary per operation.

Session handling lives entirely in :class:`inc.kernel.db.AbstractUnitOfWork`;
this subclass only wires the identity aggregates to it.
"""

from inc.kernel.db import AbstractUnitOfWork

from .repositories import IdentityRepository, OrganizationRepository, UserRepository


class IdentityUnitOfWork(AbstractUnitOfWork):
    """Exposes the identity aggregates over a single session."""

    @property
    def users(self) -> UserRepository:
        return UserRepository(self.session)

    @property
    def identities(self) -> IdentityRepository:
        return IdentityRepository(self.session)

    @property
    def organizations(self) -> OrganizationRepository:
        return OrganizationRepository(self.session)
