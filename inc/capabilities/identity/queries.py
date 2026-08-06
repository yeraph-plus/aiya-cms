"""Identity queries.

Contract source: context/spec/capabilities/identity.md §5.

Queries are read-only: they never write, emit events or count implicitly.
Credential hashes and challenge digests never leave the capability.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from inc.capabilities.identity.mappers import to_subject
from inc.capabilities.identity.models import IdentityUser
from inc.capabilities.identity.schemas import PublicProfileDTO, SubjectDTO
from inc.kernel.db import Page, UoWFactory, fetch_page


class IdentityQueries:
    def __init__(self, *, uow_factory: UoWFactory) -> None:
        self._uow_factory = uow_factory

    async def get_subject(self, user_id: str) -> SubjectDTO | None:  # type: ignore[return]
        async with self._uow_factory() as uow:
            user = await uow.session.get(IdentityUser, uuid.UUID(user_id))
            return to_subject(user) if user is not None else None

    async def find_by_login_identifier(self, identifier: str) -> SubjectDTO | None:  # type: ignore[return]
        """Look up by normalized username or email (case-insensitive)."""

        from inc.capabilities.identity.normalize import normalize_email, normalize_username

        normalized = normalize_email(identifier)
        async with self._uow_factory() as uow:
            user = (
                (
                    await uow.session.execute(
                        select(IdentityUser).where(
                            (IdentityUser.email_normalized == normalized)
                            | (IdentityUser.username_normalized == normalize_username(identifier))
                        )
                    )
                )
                .scalars()
                .first()
            )
            return to_subject(user) if user is not None else None

    async def list_users(  # type: ignore[return]
        self,
        *,
        page: int,
        size: int,
        status: str | None = None,
    ) -> Page[SubjectDTO]:
        async with self._uow_factory() as uow:
            statement = select(IdentityUser).order_by(
                IdentityUser.username_normalized, IdentityUser.id
            )
            if status is not None:
                statement = statement.where(IdentityUser.status == status)
            result = await fetch_page(uow.session, statement, page=page, size=size)
            return Page(
                items=[to_subject(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )

    async def get_public_profile(self, user_id: str) -> PublicProfileDTO | None:  # type: ignore[return]
        async with self._uow_factory() as uow:
            user = await uow.session.get(IdentityUser, uuid.UUID(user_id))
            if user is None:
                return None
            return PublicProfileDTO(
                id=str(user.id),
                username=user.username,
                display_name=user.display_name,
                avatar_asset_id=str(user.avatar_asset_id) if user.avatar_asset_id else None,
                deleted=user.status == "deleted",
            )


class CredentialAuthenticator:
    """Local password authentication adapter surface.

    Returns a SubjectDTO only for active users; banned/deleted users get
    the same indistinguishable failure. Enumerability is controlled at the
    API layer with equivalent responses and timing.
    """

    def __init__(self, *, uow_factory: UoWFactory, hasher: Any) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher

    async def authenticate_local(self, identifier: str, password: str) -> SubjectDTO | None:  # type: ignore[return]
        from inc.capabilities.identity.models import IdentityPasswordCredential
        from inc.capabilities.identity.normalize import normalize_email, normalize_username

        async with self._uow_factory() as uow:
            normalized_email = normalize_email(identifier)
            user = (
                (
                    await uow.session.execute(
                        select(IdentityUser).where(
                            (IdentityUser.email_normalized == normalized_email)
                            | (IdentityUser.username_normalized == normalize_username(identifier))
                        )
                    )
                )
                .scalars()
                .first()
            )
            if user is None or user.status != "active":
                return None
            credential = (
                (
                    await uow.session.execute(
                        select(IdentityPasswordCredential).where(
                            IdentityPasswordCredential.user_id == user.id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if credential is None or not self._hasher.verify(password, credential.password_hash):
                return None
            return to_subject(user)
