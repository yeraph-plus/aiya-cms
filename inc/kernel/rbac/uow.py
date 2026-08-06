"""RBAC unit of work."""

from inc.kernel.db import AbstractUnitOfWork
from inc.kernel.identity.repositories import UserRepository

from .repositories import PermissionRepository, RBACQueries, RoleRepository


class RBACUnitOfWork(AbstractUnitOfWork):
    @property
    def roles(self) -> RoleRepository:
        return RoleRepository(self.session)

    @property
    def permissions(self) -> PermissionRepository:
        return PermissionRepository(self.session)

    @property
    def users(self) -> UserRepository:
        return UserRepository(self.session)

    @property
    def rbac(self) -> RBACQueries:
        return RBACQueries(self.session)
