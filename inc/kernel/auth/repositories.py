"""Auth-specific persistence queries."""

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, or_, select, update

from inc.kernel.db import Repository
from inc.kernel.identity.models import Identity, User

from .models import PasswordResetToken, RefreshToken


class AuthQueries:
    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        self.session = session

    async def find_login_candidate(self, identifier: str) -> tuple[User, Identity] | None:
        result = await self.session.execute(
            select(User, Identity)
            .join(Identity, Identity.user_id == User.id)
            .where(
                Identity.provider == "password",
                or_(User.username == identifier, User.email == identifier),
            )
        )
        row = result.first()
        if row is None:
            return None
        user, identity = row
        return cast(User, user), cast(Identity, identity)

    async def reader_role_id(self) -> UUID | None:
        from inc.kernel.rbac.models import Role

        return cast(
            UUID | None,
            await self.session.scalar(select(Role.id).where(Role.name == "reader")),
        )

    async def role_names(self, user_id: UUID) -> frozenset[str]:
        from inc.kernel.rbac.repositories import RBACQueries

        return await RBACQueries(self.session).role_names_for_user(user_id)

    async def capabilities(self, user_id: UUID) -> frozenset[str]:
        from inc.kernel.rbac.repositories import RBACQueries

        return await RBACQueries(self.session).capabilities_for_user(user_id)


class RefreshTokenRepository(Repository[RefreshToken]):
    model = RefreshToken

    async def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        result = await self.session.scalars(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )
        return result.first()

    async def revoke_all_for_user(self, user_id: UUID, now: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def list_for_user(self, user_id: UUID) -> Sequence[RefreshToken]:
        result = await self.session.scalars(
            select(RefreshToken).where(RefreshToken.user_id == user_id)
        )
        return result.all()

    async def purge_expired(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            delete(RefreshToken).where(
                RefreshToken.expires_at < cutoff,
                RefreshToken.revoked_at.is_not(None),
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)


class PasswordResetTokenRepository(Repository[PasswordResetToken]):
    model = PasswordResetToken

    async def get_by_hash_for_update(self, token_hash: str) -> PasswordResetToken | None:
        result = await self.session.scalars(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash)
            .with_for_update()
        )
        return result.first()

    async def consume_for_user(self, user_id: UUID, now: datetime) -> None:
        await self.session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )

    async def purge_expired(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            delete(PasswordResetToken).where(PasswordResetToken.expires_at < cutoff)
        )
        return int(getattr(result, "rowcount", 0) or 0)
