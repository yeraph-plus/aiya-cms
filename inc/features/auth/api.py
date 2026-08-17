"""Authentication feature gateway used by the HTTP composition root."""

from __future__ import annotations

from typing import Any

from inc.capabilities.access import AssignDefaultUserRole
from inc.capabilities.access import CommandContext as AccessCommandContext
from inc.capabilities.identity import IdentityQueries
from inc.capabilities.identity.commands import (
    CommandContext as IdentityCommandContext,
)
from inc.capabilities.identity.commands import (
    RegisterLocalUser,
    RequestPasswordReset,
    ResetPassword,
    VerifyEmail,
)
from inc.capabilities.identity.schemas import ChallengeDTO, SubjectDTO
from inc.capabilities.notification import AuthChallengeInput, AuthChallengeNotifier
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import OutboxWriter
from inc.kernel.security import PasswordHasher
from inc.kernel.time import Clock


class AuthService:
    """Compose identity, access and notification without owning their data."""

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        clock: Clock,
        outbox: OutboxWriter,
        hasher: PasswordHasher,
        identity_queries: IdentityQueries,
        access_queries: Any,
        permission_registry: Any,
        notification_auth: AuthChallengeNotifier | None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._outbox = outbox
        self._hasher = hasher
        self._identity_queries = identity_queries
        self._access_queries = access_queries
        self._permission_registry = permission_registry
        self._notification_auth = notification_auth

    def _identity_context(self, trace_id: str | None) -> IdentityCommandContext:
        return IdentityCommandContext(
            uow_factory=self._uow_factory,
            clock=self._clock,
            outbox=self._outbox,
            hasher=self._hasher,
            audit_trace_id=trace_id,
        )

    def _access_context(self, trace_id: str | None) -> AccessCommandContext:
        return AccessCommandContext(
            uow_factory=self._uow_factory,
            clock=self._clock,
            outbox=self._outbox,
            permissions=self._permission_registry,
            subject_exists=_IdentitySubjectExists(self._identity_queries),
            audit_actor_id="system",
            audit_trace_id=trace_id,
        )

    async def register(
        self,
        *,
        username: str,
        email: str,
        password: str,
        display_name: str | None,
        trace_id: str | None,
    ) -> SubjectDTO:
        if not await self._access_queries.role_exists("user"):
            raise KernelError(
                code="auth.registration_unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="registration roles are not initialized",
            )
        identity = RegisterLocalUser(self._identity_context(trace_id))
        access = self._access_context(trace_id)
        async with self._uow_factory() as uow:
            result = await identity.register_in_uow(
                uow,
                username=username,
                email=email,
                password=password,
                display_name=display_name,
                issue_email_challenge=True,
            )
            try:
                await AssignDefaultUserRole(access).assign_in_uow(
                    uow,
                    subject_type="identity",
                    subject_id=result.subject.id,
                )
            except KernelError as exc:
                if exc.code == "access.not_found":
                    raise KernelError(
                        code="auth.registration_unavailable",
                        category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                        message="registration roles are not initialized",
                    ) from exc
                raise
            await uow.commit()
        await self._send_challenge(
            result.challenge, username=result.subject.username, trace_id=trace_id
        )
        return result.subject

    async def verify_email(self, *, token: str, trace_id: str | None) -> SubjectDTO:
        return await VerifyEmail(self._identity_context(trace_id))(token=token)

    async def request_password_reset(self, *, identifier: str, trace_id: str | None) -> None:
        challenge = await RequestPasswordReset(self._identity_context(trace_id))(
            identifier=identifier
        )
        if challenge is None:
            return
        subject = await self._identity_queries.get_subject(challenge.id)
        if subject is not None:
            await self._send_challenge(
                challenge,
                username=subject.username,
                trace_id=trace_id,
            )

    async def reset_password(
        self, *, token: str, new_password: str, trace_id: str | None
    ) -> SubjectDTO:
        return await ResetPassword(self._identity_context(trace_id))(
            token=token, new_password=new_password
        )

    async def _send_challenge(
        self,
        challenge: ChallengeDTO | None,
        *,
        username: str,
        trace_id: str | None,
    ) -> None:
        if challenge is None or not challenge.token:
            return
        if self._notification_auth is None:
            raise KernelError(
                code="auth.challenge_delivery_unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="out-of-band authentication challenge delivery is unavailable",
            )
        await self._notification_auth.send(
            AuthChallengeInput(
                subject_id=challenge.id,
                purpose=challenge.purpose,  # type: ignore[arg-type]
                username=username,
                token=challenge.token,
                expires_at=challenge.expires_at,
            ),
            trace_id=trace_id,
        )


class _IdentitySubjectExists:
    """Consumer-side access Port; identity remains opaque to access."""

    def __init__(self, queries: IdentityQueries) -> None:
        self._queries = queries

    async def exists(self, subject_type: str, subject_id: str) -> bool:
        return (
            subject_type == "identity" and await self._queries.get_subject(subject_id) is not None
        )
