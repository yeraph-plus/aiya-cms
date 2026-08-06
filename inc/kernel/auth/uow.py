"""Auth transaction boundary."""

from inc.kernel.db import AbstractUnitOfWork
from inc.kernel.identity.repositories import IdentityRepository, UserRepository
from inc.kernel.rbac.repositories import RBACQueries, RoleRepository

from .repositories import AuthQueries, PasswordResetTokenRepository, RefreshTokenRepository


class AuthUnitOfWork(AbstractUnitOfWork):
    @property
    def users(self) -> UserRepository:
        return UserRepository(self.session)

    @property
    def identities(self) -> IdentityRepository:
        return IdentityRepository(self.session)

    @property
    def roles(self) -> RoleRepository:
        return RoleRepository(self.session)

    @property
    def auth(self) -> AuthQueries:
        return AuthQueries(self.session)

    @property
    def refresh_tokens(self) -> RefreshTokenRepository:
        return RefreshTokenRepository(self.session)

    @property
    def password_reset_tokens(self) -> PasswordResetTokenRepository:
        return PasswordResetTokenRepository(self.session)

    @property
    def rbac(self) -> RBACQueries:
        return RBACQueries(self.session)
