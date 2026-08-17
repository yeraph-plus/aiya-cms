"""Identity commands.

Contract source: context/spec/capabilities/identity.md §4/§8.

Every command runs in one UoW: business state, business event outbox rows
and audit envelopes commit atomically. Handlers never receive a Session;
they receive a CommandContext with a UoW factory, clock, hasher and the
kernel OutboxWriter.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from inc.capabilities.identity.mappers import to_subject
from inc.capabilities.identity.models import (
    IdentityChallenge,
    IdentityLoginIdentity,
    IdentityPasswordCredential,
    IdentityUser,
)
from inc.capabilities.identity.normalize import normalize_email, normalize_username
from inc.capabilities.identity.policies import HASH_VERSION, PasswordPolicy, validate_password
from inc.capabilities.identity.schemas import (
    ChallengeDTO,
    RegistrationResult,
    SubjectDTO,
    UpdateProfileInput,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.security import PasswordHasher, random_token
from inc.kernel.time import Clock

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"

CHALLENGE_TTL_SECONDS = 15 * 60
CHALLENGE_MAX_ATTEMPTS = 5
LOCAL_PROVIDER = "local"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    hasher: PasswordHasher
    outbox: OutboxWriter
    password_policy: PasswordPolicy = field(default_factory=PasswordPolicy)
    audit_actor_id: str | None = None
    audit_trace_id: str | None = None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ensure_utc(value: Any) -> Any:
    """SQLite drops tzinfo; persisted times are always UTC."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _conflict(message: str) -> KernelError:
    return KernelError(
        code="identity.duplicate_identifier", category=ErrorCategory.CONFLICT, message=message
    )


def _not_found(message: str) -> KernelError:
    return KernelError(code="identity.not_found", category=ErrorCategory.NOT_FOUND, message=message)


async def _append_audit(
    uow: UnitOfWork,
    ctx: CommandContext,
    *,
    action: str,
    target_type: str,
    target_id: str,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=ctx.clock.utc_now(),
            producer="identity",
            aggregate_type="identity",
            aggregate_id=target_id,
            trace_id=ctx.audit_trace_id,
            payload={
                "action": action,
                "outcome": outcome,
                "occurred_at": ctx.clock.utc_now().isoformat(),
                "actor_type": "user" if ctx.audit_actor_id else None,
                "actor_id": ctx.audit_actor_id,
                "target_type": target_type,
                "target_id": target_id,
                "trace_id": ctx.audit_trace_id,
                "details": details or {},
            },
        ),
    )


async def _append_event(
    uow: UnitOfWork,
    ctx: CommandContext,
    *,
    event_key: str,
    payload: dict[str, Any],
    aggregate_id: str,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=event_key,
            occurred_at=ctx.clock.utc_now(),
            producer="identity",
            aggregate_type="identity",
            aggregate_id=aggregate_id,
            trace_id=ctx.audit_trace_id,
            payload=payload,
        ),
    )


async def _consume_challenge(
    uow: UnitOfWork, ctx: CommandContext, challenge: IdentityChallenge | None
) -> None:
    """Consume a one-time challenge, persisting failed attempts.

    A failed validation raises ``KernelError`` out of the UoW block, which
    rolls back uncommitted changes. The attempt counter is therefore
    committed before re-raising so brute-force limiting actually counts
    failed attempts and ``challenge_attempts_exceeded`` can fire.
    """

    now = ctx.clock.utc_now()
    if challenge is None:
        raise KernelError(
            code="identity.challenge_invalid",
            category=ErrorCategory.VALIDATION,
            message="invalid challenge token",
        )
    challenge.attempts += 1
    failure: KernelError | None = None
    if challenge.consumed_at is not None:
        failure = KernelError(
            code="identity.challenge_consumed",
            category=ErrorCategory.VALIDATION,
            message="challenge already consumed",
        )
    elif _ensure_utc(challenge.expires_at) < now:
        failure = KernelError(
            code="identity.challenge_expired",
            category=ErrorCategory.VALIDATION,
            message="challenge expired",
        )
    elif challenge.attempts > challenge.max_attempts:
        failure = KernelError(
            code="identity.challenge_attempts_exceeded",
            category=ErrorCategory.RATE_LIMITED,
            message="too many attempts",
        )
    if failure is not None:
        # Persist the increment before the exception rolls the UoW back.
        await uow.commit()
        raise failure
    challenge.consumed_at = now


class RegisterLocalUser:
    """Creates a user with local login identity and password credential."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self,
        *,
        username: str,
        email: str,
        password: str,
        display_name: str | None = None,
        issue_email_challenge: bool = False,
    ) -> RegistrationResult:
        async with self._ctx.uow_factory() as uow:
            result = await self.register_in_uow(
                uow,
                username=username,
                email=email,
                password=password,
                display_name=display_name,
                issue_email_challenge=issue_email_challenge,
            )
            await uow.commit()
            return result

    async def register_in_uow(
        self,
        uow: UnitOfWork,
        *,
        username: str,
        email: str,
        password: str,
        display_name: str | None = None,
        issue_email_challenge: bool = False,
    ) -> RegistrationResult:
        """Register without committing, for composition-root transactions.

        The caller owns the surrounding transaction and may append a
        consumer-owned projection (for example the baseline access role)
        before committing identity and projection state together.
        """

        validate_password(self._ctx.password_policy, password)
        username_normalized = normalize_username(username)
        email_normalized = normalize_email(email)

        user = IdentityUser(
            username=username,
            username_normalized=username_normalized,
            email_display=email,
            email_normalized=email_normalized,
            display_name=display_name,
            status="active",
        )
        uow.session.add(user)
        try:
            await uow.session.flush()  # assigns user.id; unique violations surface here
        except IntegrityError as exc:
            raise _conflict("username or email is already registered") from exc
        uow.session.add(
            IdentityLoginIdentity(
                user_id=user.id, provider=LOCAL_PROVIDER, provider_subject=username_normalized
            )
        )
        uow.session.add(
            IdentityPasswordCredential(
                user_id=user.id,
                password_hash=self._ctx.hasher.hash(password),
                hash_version=HASH_VERSION,
                changed_at=self._ctx.clock.utc_now(),
            )
        )

        challenge: ChallengeDTO | None = None
        if issue_email_challenge:
            token = random_token()
            uow.session.add(
                IdentityChallenge(
                    user_id=user.id,
                    purpose="email_verification",
                    token_digest=_digest(token),
                    expires_at=self._ctx.clock.utc_now() + timedelta(seconds=CHALLENGE_TTL_SECONDS),
                    attempts=0,
                    max_attempts=CHALLENGE_MAX_ATTEMPTS,
                )
            )
            challenge = ChallengeDTO(
                id=str(user.id),
                purpose="email_verification",
                expires_at=self._ctx.clock.utc_now() + timedelta(seconds=CHALLENGE_TTL_SECONDS),
                max_attempts=CHALLENGE_MAX_ATTEMPTS,
                token=token,
            )

        await _append_event(
            uow,
            self._ctx,
            event_key="identity.user_registered.v1",
            payload={"subject_id": str(user.id), "username": username},
            aggregate_id=str(user.id),
        )
        await _append_audit(
            uow,
            self._ctx,
            action="identity.user.register",
            target_type="user",
            target_id=str(user.id),
        )
        return RegistrationResult(subject=to_subject(user), challenge=challenge)


class VerifyEmail:
    """One-time challenge consumption for email verification."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, token: str) -> SubjectDTO:  # type: ignore[return]
        async with self._ctx.uow_factory() as uow:
            challenge = (
                (
                    await uow.session.execute(
                        select(IdentityChallenge).where(
                            IdentityChallenge.purpose == "email_verification",
                            IdentityChallenge.token_digest == _digest(token),
                        )
                    )
                )
                .scalars()
                .first()
            )
            await self._consume(uow, challenge)
            user = await uow.session.get(IdentityUser, challenge.user_id)
            user.email_verified_at = self._ctx.clock.utc_now()
            await _append_event(
                uow,
                self._ctx,
                event_key="identity.email_verified.v1",
                payload={"subject_id": str(user.id)},
                aggregate_id=str(user.id),
            )
            await _append_audit(
                uow,
                self._ctx,
                action="identity.email.verified",
                target_type="user",
                target_id=str(user.id),
            )
            await uow.commit()
            return to_subject(user)

    async def _consume(self, uow: UnitOfWork, challenge: IdentityChallenge | None) -> None:
        await _consume_challenge(uow, self._ctx, challenge)


class RequestPasswordReset:
    """Issues a one-time ``password_reset`` challenge for an active user.

    Contract source: context/spec/capabilities/identity.md §4.

    Enumeration-safe: unknown, banned or deleted identifiers return
    ``None`` — the same external result as a successful request.
    Outstanding unconsumed reset challenges are superseded, so only the
    newest token stays valid. The token is returned to the in-process
    caller exactly once; out-of-band delivery is triggered by the API
    composition root through notification's public challenge notifier
    (identity never imports notification), and
    events/audits never carry the token.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, identifier: str) -> ChallengeDTO | None:  # type: ignore[return]
        username_normalized = normalize_username(identifier)
        email_normalized = normalize_email(identifier)
        async with self._ctx.uow_factory() as uow:
            user = (
                (
                    await uow.session.execute(
                        select(IdentityUser).where(
                            IdentityUser.status == "active",
                            or_(
                                IdentityUser.username_normalized == username_normalized,
                                IdentityUser.email_normalized == email_normalized,
                            ),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if user is None:
                return None
            now = self._ctx.clock.utc_now()
            outstanding = (
                (
                    await uow.session.execute(
                        select(IdentityChallenge).where(
                            IdentityChallenge.user_id == user.id,
                            IdentityChallenge.purpose == "password_reset",
                            IdentityChallenge.consumed_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for old in outstanding:
                old.consumed_at = now
            token = random_token()
            expires_at = now + timedelta(seconds=CHALLENGE_TTL_SECONDS)
            uow.session.add(
                IdentityChallenge(
                    user_id=user.id,
                    purpose="password_reset",
                    token_digest=_digest(token),
                    expires_at=expires_at,
                    attempts=0,
                    max_attempts=CHALLENGE_MAX_ATTEMPTS,
                )
            )
            await _append_audit(
                uow,
                self._ctx,
                action="identity.password.reset_requested",
                target_type="user",
                target_id=str(user.id),
            )
            await uow.commit()
            return ChallengeDTO(
                id=str(user.id),
                purpose="password_reset",
                expires_at=expires_at,
                max_attempts=CHALLENGE_MAX_ATTEMPTS,
                token=token,
            )


class ResetPassword:
    """Password reset via one-time challenge token."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, token: str, new_password: str) -> SubjectDTO:  # type: ignore[return]
        validate_password(self._ctx.password_policy, new_password)
        async with self._ctx.uow_factory() as uow:
            challenge = (
                (
                    await uow.session.execute(
                        select(IdentityChallenge).where(
                            IdentityChallenge.purpose == "password_reset",
                            IdentityChallenge.token_digest == _digest(token),
                        )
                    )
                )
                .scalars()
                .first()
            )
            await self._verify_and_consume(uow, challenge)
            credential = (
                (
                    await uow.session.execute(
                        select(IdentityPasswordCredential).where(
                            IdentityPasswordCredential.user_id == challenge.user_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if credential is None:
                # OAuth-only accounts have no local password credential; a
                # reset token cannot change what does not exist.
                raise KernelError(
                    code="identity.no_local_credential",
                    category=ErrorCategory.VALIDATION,
                    message="account has no local password credential",
                )
            credential.password_hash = self._ctx.hasher.hash(new_password)
            credential.hash_version = HASH_VERSION
            credential.changed_at = self._ctx.clock.utc_now()
            await _append_event(
                uow,
                self._ctx,
                event_key="identity.password_changed.v1",
                payload={"subject_id": str(challenge.user_id), "method": "reset"},
                aggregate_id=str(challenge.user_id),
            )
            await _append_audit(
                uow,
                self._ctx,
                action="identity.password.reset",
                target_type="user",
                target_id=str(challenge.user_id),
            )
            await uow.commit()
            user = await uow.session.get(IdentityUser, challenge.user_id)
            return to_subject(user)

    async def _verify_and_consume(
        self, uow: UnitOfWork, challenge: IdentityChallenge | None
    ) -> None:
        await _consume_challenge(uow, self._ctx, challenge)


class ChangePassword:
    """Self-service password change requiring the current password."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, user_id: str, current_password: str, new_password: str) -> None:
        validate_password(self._ctx.password_policy, new_password)
        async with self._ctx.uow_factory() as uow:
            credential = (
                (
                    await uow.session.execute(
                        select(IdentityPasswordCredential).where(
                            IdentityPasswordCredential.user_id == uuid.UUID(user_id)
                        )
                    )
                )
                .scalars()
                .first()
            )
            if credential is None or not self._ctx.hasher.verify(
                current_password, credential.password_hash
            ):
                raise KernelError(
                    code="identity.password_mismatch",
                    category=ErrorCategory.VALIDATION,
                    message="current password is incorrect",
                )
            credential.password_hash = self._ctx.hasher.hash(new_password)
            credential.hash_version = HASH_VERSION
            credential.changed_at = self._ctx.clock.utc_now()
            await _append_event(
                uow,
                self._ctx,
                event_key="identity.password_changed.v1",
                payload={"subject_id": user_id, "method": "change"},
                aggregate_id=user_id,
            )
            await _append_audit(
                uow,
                self._ctx,
                action="identity.password.changed",
                target_type="user",
                target_id=user_id,
            )
            await uow.commit()


class UpdateProfile:
    """Whitelisted profile updates only; unknown fields are rejected."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, user_id: str, changes: UpdateProfileInput) -> SubjectDTO:  # type: ignore[return]
        async with self._ctx.uow_factory() as uow:
            user = await uow.session.get(IdentityUser, uuid.UUID(user_id))
            if user is None:
                raise _not_found("user not found")
            changed: list[str] = []
            if "display_name" in changes.model_fields_set:
                user.display_name = changes.display_name
                changed.append("display_name")
            if "avatar_asset_id" in changes.model_fields_set:
                user.avatar_asset_id = (
                    uuid.UUID(changes.avatar_asset_id) if changes.avatar_asset_id else None
                )
                changed.append("avatar_asset_id")
            if changed:
                await _append_audit(
                    uow,
                    self._ctx,
                    action="identity.profile.updated",
                    target_type="user",
                    target_id=user_id,
                    details={"changed": changed},
                )
            await uow.commit()
            return to_subject(user)


class BanUser:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, user_id: str, reason: str | None = None) -> SubjectDTO:  # type: ignore[return]
        async with self._ctx.uow_factory() as uow:
            user = await uow.session.get(IdentityUser, uuid.UUID(user_id))
            if user is None:
                raise _not_found("user not found")
            if user.status == "deleted":
                raise _conflict("deleted users cannot be banned")
            user.status = "banned"
            await _append_event(
                uow,
                self._ctx,
                event_key="identity.user_banned.v1",
                payload={"subject_id": user_id, "reason": reason},
                aggregate_id=user_id,
            )
            await _append_audit(
                uow,
                self._ctx,
                action="identity.user.banned",
                target_type="user",
                target_id=user_id,
                details={"reason": reason} if reason else None,
            )
            await uow.commit()
            return to_subject(user)


class UnbanUser:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, user_id: str) -> SubjectDTO:  # type: ignore[return]
        async with self._ctx.uow_factory() as uow:
            user = await uow.session.get(IdentityUser, uuid.UUID(user_id))
            if user is None:
                raise _not_found("user not found")
            if user.status != "banned":
                raise KernelError(
                    code="identity.not_banned",
                    category=ErrorCategory.CONFLICT,
                    message="user is not banned",
                )
            user.status = "active"
            await _append_event(
                uow,
                self._ctx,
                event_key="identity.user_unbanned.v1",
                payload={"subject_id": user_id},
                aggregate_id=user_id,
            )
            await _append_audit(
                uow,
                self._ctx,
                action="identity.user.unbanned",
                target_type="user",
                target_id=user_id,
            )
            await uow.commit()
            return to_subject(user)


class DeleteUser:
    """Archives a user; physical purge is out of scope and audit-safe."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, user_id: str) -> None:
        async with self._ctx.uow_factory() as uow:
            user = await uow.session.get(IdentityUser, uuid.UUID(user_id))
            if user is None:
                raise _not_found("user not found")
            user.status = "deleted"
            user.deleted_at = self._ctx.clock.utc_now()
            await _append_event(
                uow,
                self._ctx,
                event_key="identity.user_deleted.v1",
                payload={"subject_id": user_id},
                aggregate_id=user_id,
            )
            await _append_audit(
                uow,
                self._ctx,
                action="identity.user.deleted",
                target_type="user",
                target_id=user_id,
            )
            await uow.commit()


class LinkLoginIdentity:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, user_id: str, provider: str, provider_subject: str) -> None:
        async with self._ctx.uow_factory() as uow:
            try:
                uow.session.add(
                    IdentityLoginIdentity(
                        user_id=uuid.UUID(user_id),
                        provider=provider,
                        provider_subject=provider_subject,
                    )
                )
                await uow.session.flush()
            except IntegrityError as exc:
                await uow.rollback()
                raise _conflict("login identity already linked") from exc
            await uow.commit()


class UnlinkLoginIdentity:
    """Removes a login identity; keeps at least one usable login method."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, user_id: str, provider: str, provider_subject: str) -> None:
        async with self._ctx.uow_factory() as uow:
            identity = (
                (
                    await uow.session.execute(
                        select(IdentityLoginIdentity).where(
                            IdentityLoginIdentity.user_id == uuid.UUID(user_id),
                            IdentityLoginIdentity.provider == provider,
                            IdentityLoginIdentity.provider_subject == provider_subject,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if identity is None:
                raise _not_found("login identity not found")
            remaining = (
                (
                    await uow.session.execute(
                        select(IdentityLoginIdentity.id).where(
                            IdentityLoginIdentity.user_id == uuid.UUID(user_id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(remaining) <= 1:
                raise _conflict("user must keep at least one login identity")
            await uow.session.delete(identity)
            await uow.commit()
