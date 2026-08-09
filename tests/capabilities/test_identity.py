"""Identity capability tests.

Contract source: context/spec/capabilities/identity.md §10.

Runs against SQLite with the kernel UoW/outbox code paths.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.identity.commands import (
    BanUser,
    ChangePassword,
    CommandContext,
    DeleteUser,
    LinkLoginIdentity,
    RegisterLocalUser,
    RequestPasswordReset,
    ResetPassword,
    UnbanUser,
    UnlinkLoginIdentity,
    VerifyEmail,
)
from inc.capabilities.identity.diagnostics import IdentityDiagnostics
from inc.capabilities.identity.events import IDENTITY_EVENT_SCHEMAS
from inc.capabilities.identity.models import IdentityUser
from inc.capabilities.identity.queries import CredentialAuthenticator, IdentityQueries
from inc.capabilities.identity.schemas import UpdateProfileInput
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import (
    EventSchemaRegistry,
    OutboxWriter,
)
from inc.kernel.security import Argon2PasswordHasher


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in IDENTITY_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def identity_ctx(
    uow_factory: UoWFactory,
    clock: Any,
    schema_registry: EventSchemaRegistry,
) -> CommandContext:
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=Argon2PasswordHasher(),
        outbox=OutboxWriter(schema_registry, clock),
        audit_actor_id="test-admin",
        audit_trace_id="trace-1",
    )


@pytest.fixture
def queries(uow_factory: UoWFactory) -> IdentityQueries:
    return IdentityQueries(uow_factory=uow_factory)


async def test_register_normalizes_identifiers(
    identity_ctx: CommandContext, queries: IdentityQueries
) -> None:
    result = await RegisterLocalUser(identity_ctx)(
        username="Alice ", email="Alice@Example.COM", password="correct horse battery"
    )
    assert result.subject.username == "Alice "
    assert result.subject.email_verified is False
    subject = await queries.find_by_login_identifier("ALICE@example.com")
    assert subject is not None and subject.id == result.subject.id
    subject2 = await queries.find_by_login_identifier("alice")
    assert subject2 is not None and subject2.id == result.subject.id


async def test_concurrent_registration_same_username_only_one_wins(
    identity_ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    command = RegisterLocalUser(identity_ctx)
    await command(username="bob", email="bob@example.com", password="password-123")
    with pytest.raises(KernelError) as excinfo:
        await command(username="BOB", email="other@example.com", password="password-456")
    assert excinfo.value.category.value == "conflict"
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(IdentityUser.id))).scalars().all()
    assert len(rows) == 1


async def test_email_challenge_verifies_and_blocks_replay(
    identity_ctx: CommandContext, queries: IdentityQueries, clock: Any
) -> None:
    result = await RegisterLocalUser(identity_ctx)(
        username="carol",
        email="carol@example.com",
        password="password-123",
        issue_email_challenge=True,
    )
    assert result.challenge is not None and result.challenge.token is not None

    subject = await VerifyEmail(identity_ctx)(token=result.challenge.token)
    assert subject.email_verified is True

    # replay is rejected
    with pytest.raises(KernelError) as excinfo:
        await VerifyEmail(identity_ctx)(token=result.challenge.token)
    assert excinfo.value.code == "identity.challenge_consumed"


async def test_challenge_expiry_and_wrong_token_are_rejected(
    identity_ctx: CommandContext, clock: Any
) -> None:
    result = await RegisterLocalUser(identity_ctx)(
        username="dave",
        email="dave@example.com",
        password="password-123",
        issue_email_challenge=True,
    )
    token = result.challenge.token if result.challenge else None
    assert token is not None

    with pytest.raises(KernelError) as excinfo:
        await VerifyEmail(identity_ctx)(token="guessed-token")
    assert excinfo.value.code == "identity.challenge_invalid"

    clock.advance(timedelta(minutes=30))
    with pytest.raises(KernelError) as excinfo:
        await VerifyEmail(identity_ctx)(token=token)
    assert excinfo.value.code == "identity.challenge_expired"


async def test_failed_challenge_attempts_persist_for_bruteforce_lockout(
    identity_ctx: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    """A failed challenge verification must persist the attempt count.

    The attempt increment used to be rolled back by the UoW when the
    validation KernelError propagated, so ``challenge_attempts_exceeded``
    could never fire. The increment must survive the failed attempt.
    """

    result = await RegisterLocalUser(identity_ctx)(
        username="zoe",
        email="zoe@example.com",
        password="password-123",
        issue_email_challenge=True,
    )
    assert result.challenge is not None and result.challenge.token is not None

    from inc.capabilities.identity.models import IdentityChallenge

    async def attempts_for(token: str) -> int:
        from inc.capabilities.identity.commands import _digest

        async with uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(IdentityChallenge).where(
                            IdentityChallenge.purpose == "email_verification",
                            IdentityChallenge.token_digest == _digest(token),
                        )
                    )
                )
                .scalars()
                .one()
            )
            return row.attempts

    # Expire the challenge, then a failed verification must still count.
    clock.advance(timedelta(minutes=30))
    with pytest.raises(KernelError):
        await VerifyEmail(identity_ctx)(token=result.challenge.token)
    assert await attempts_for(result.challenge.token) == 1

    with pytest.raises(KernelError):
        await VerifyEmail(identity_ctx)(token=result.challenge.token)
    assert await attempts_for(result.challenge.token) == 2

    # Once consumed, a replay also counts against the challenge.
    fresh = await RegisterLocalUser(identity_ctx)(
        username="zoe2",
        email="zoe2@example.com",
        password="password-123",
        issue_email_challenge=True,
    )
    assert fresh.challenge is not None and fresh.challenge.token is not None
    await VerifyEmail(identity_ctx)(token=fresh.challenge.token)
    with pytest.raises(KernelError) as excinfo:
        await VerifyEmail(identity_ctx)(token=fresh.challenge.token)
    assert excinfo.value.code == "identity.challenge_consumed"
    assert await attempts_for(fresh.challenge.token) == 2


async def test_ban_blocks_authentication_and_delete_archives(
    identity_ctx: CommandContext,
    queries: IdentityQueries,
    uow_factory: UoWFactory,
) -> None:
    result = await RegisterLocalUser(identity_ctx)(
        username="erin", email="erin@example.com", password="password-123"
    )
    authenticator = CredentialAuthenticator(uow_factory=uow_factory, hasher=Argon2PasswordHasher())
    assert await authenticator.authenticate_local("erin", "password-123") is not None

    await BanUser(identity_ctx)(user_id=result.subject.id, reason="spam")
    assert await authenticator.authenticate_local("erin", "password-123") is None
    subject = await queries.get_subject(result.subject.id)
    assert subject is not None and subject.status == "banned"

    await DeleteUser(identity_ctx)(user_id=result.subject.id)
    profile = await queries.get_public_profile(result.subject.id)
    assert profile is not None and profile.deleted


async def test_password_change_requires_current_password(
    identity_ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    result = await RegisterLocalUser(identity_ctx)(
        username="frank", email="frank@example.com", password="old-password-1"
    )
    with pytest.raises(KernelError):
        await ChangePassword(identity_ctx)(
            user_id=result.subject.id,
            current_password="wrong",
            new_password="new-password-2",
        )
    with pytest.raises(ValueError):
        await ChangePassword(identity_ctx)(
            user_id=result.subject.id,
            current_password="old-password-1",
            new_password="short",
        )
    await ChangePassword(identity_ctx)(
        user_id=result.subject.id,
        current_password="old-password-1",
        new_password="new-password-2",
    )
    authenticator = CredentialAuthenticator(uow_factory=uow_factory, hasher=Argon2PasswordHasher())
    assert await authenticator.authenticate_local("frank", "new-password-2") is not None


async def test_unlink_keeps_at_least_one_login_method(
    identity_ctx: CommandContext,
) -> None:
    result = await RegisterLocalUser(identity_ctx)(
        username="grace", email="grace@example.com", password="password-123"
    )
    with pytest.raises(KernelError) as excinfo:
        await UnlinkLoginIdentity(identity_ctx)(
            user_id=result.subject.id, provider="local", provider_subject="grace"
        )
    assert excinfo.value.category.value == "conflict"

    await LinkLoginIdentity(identity_ctx)(
        user_id=result.subject.id, provider="external", provider_subject="ext-1"
    )
    await UnlinkLoginIdentity(identity_ctx)(
        user_id=result.subject.id, provider="local", provider_subject="grace"
    )


async def test_profile_update_rejects_unknown_fields(
    identity_ctx: CommandContext,
) -> None:
    with pytest.raises(ValidationError):
        UpdateProfileInput.model_validate({"secret_field": "x"})
    result = await RegisterLocalUser(identity_ctx)(
        username="henry", email="henry@example.com", password="password-123"
    )
    assert result.subject.display_name is None


async def test_password_reset_request_issues_challenge_and_reset_rotates_credential(
    identity_ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    result = await RegisterLocalUser(identity_ctx)(
        username="judy", email="judy@example.com", password="old-password-1"
    )
    challenge = await RequestPasswordReset(identity_ctx)(identifier="JUDY@example.com")
    assert challenge is not None and challenge.token is not None
    assert challenge.purpose == "password_reset"
    assert challenge.max_attempts > 0

    subject = await ResetPassword(identity_ctx)(
        token=challenge.token, new_password="new-password-2"
    )
    assert subject.id == result.subject.id
    authenticator = CredentialAuthenticator(uow_factory=uow_factory, hasher=Argon2PasswordHasher())
    assert await authenticator.authenticate_local("judy", "old-password-1") is None
    assert await authenticator.authenticate_local("judy", "new-password-2") is not None


async def test_password_reset_request_is_enumeration_safe(
    identity_ctx: CommandContext,
) -> None:
    # unknown identifier
    assert await RequestPasswordReset(identity_ctx)(identifier="ghost@example.com") is None

    banned = await RegisterLocalUser(identity_ctx)(
        username="kate", email="kate@example.com", password="password-123"
    )
    await BanUser(identity_ctx)(user_id=banned.subject.id, reason="spam")
    assert await RequestPasswordReset(identity_ctx)(identifier="kate") is None
    await UnbanUser(identity_ctx)(user_id=banned.subject.id)
    assert await RequestPasswordReset(identity_ctx)(identifier="kate") is not None

    deleted = await RegisterLocalUser(identity_ctx)(
        username="ken", email="ken@example.com", password="password-123"
    )
    await DeleteUser(identity_ctx)(user_id=deleted.subject.id)
    assert await RequestPasswordReset(identity_ctx)(identifier="ken@example.com") is None


async def test_password_reset_request_supersedes_previous_challenge(
    identity_ctx: CommandContext,
) -> None:
    await RegisterLocalUser(identity_ctx)(
        username="leo", email="leo@example.com", password="password-123"
    )
    first = await RequestPasswordReset(identity_ctx)(identifier="leo")
    second = await RequestPasswordReset(identity_ctx)(identifier="leo@example.com")
    assert first is not None and first.token is not None
    assert second is not None and second.token is not None

    with pytest.raises(KernelError) as excinfo:
        await ResetPassword(identity_ctx)(token=first.token, new_password="new-password-2")
    assert excinfo.value.code == "identity.challenge_consumed"

    await ResetPassword(identity_ctx)(token=second.token, new_password="new-password-2")


async def test_password_reset_rejects_email_verification_token(
    identity_ctx: CommandContext,
) -> None:
    result = await RegisterLocalUser(identity_ctx)(
        username="mike",
        email="mike@example.com",
        password="password-123",
        issue_email_challenge=True,
    )
    assert result.challenge is not None and result.challenge.token is not None
    with pytest.raises(KernelError) as excinfo:
        await ResetPassword(identity_ctx)(
            token=result.challenge.token, new_password="new-password-2"
        )
    assert excinfo.value.code == "identity.challenge_invalid"


async def test_password_reset_rejects_oauth_only_account(
    identity_ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    """An OAuth-only account (no local credential) must fail reset cleanly."""

    from inc.capabilities.identity.commands import RegisterLocalUser
    from inc.capabilities.identity.models import IdentityLoginIdentity

    # OAuth-only user: register locally, then unlink the local credential path
    # by adding an external identity and removing the local credential row.
    registered = await RegisterLocalUser(identity_ctx)(
        username="olivia",
        email="olivia@example.com",
        password="password-123",
    )
    await LinkLoginIdentity(identity_ctx)(
        user_id=registered.subject.id, provider="external", provider_subject="ext-olivia"
    )
    async with uow_factory() as uow:
        from inc.capabilities.identity.models import IdentityPasswordCredential

        await uow.session.execute(
            IdentityPasswordCredential.__table__.delete().where(
                IdentityPasswordCredential.user_id == uuid.UUID(registered.subject.id)
            )
        )
        await uow.commit()

    challenge = await RequestPasswordReset(identity_ctx)(identifier="olivia")
    assert challenge is not None and challenge.token is not None
    with pytest.raises(KernelError) as excinfo:
        await ResetPassword(identity_ctx)(token=challenge.token, new_password="new-password-2")
    assert excinfo.value.code == "identity.no_local_credential"

    # The account still has its external login method intact.
    async with uow_factory() as uow:
        identities = (await uow.session.execute(select(IdentityLoginIdentity))).scalars().all()
        assert any(i.user_id == uuid.UUID(registered.subject.id) for i in identities)


async def test_diagnostics_are_readonly(
    identity_ctx: CommandContext,
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    await RegisterLocalUser(identity_ctx)(
        username="ivan", email="ivan@example.com", password="password-123"
    )
    diagnostics = IdentityDiagnostics(uow_factory=uow_factory, clock=clock)
    async with uow_factory() as uow:
        users_before = len((await uow.session.execute(select(IdentityUser.id))).scalars().all())
    results = await diagnostics.run()
    async with uow_factory() as uow:
        users_after = len((await uow.session.execute(select(IdentityUser.id))).scalars().all())
    assert users_before == users_after
    assert any(r.code == "identity.no_login_method" for r in results)


async def test_challenge_token_not_leaked_in_repr(identity_ctx: CommandContext) -> None:
    """The one-time challenge token must not appear in repr()/str() of the
    DTO, so accidental logging or traceback dumps do not leak the secret."""
    from inc.capabilities.identity.schemas import ChallengeDTO

    dto = ChallengeDTO(
        id="challenge-1",
        purpose="verify_email",
        expires_at=datetime.now(),
        token="super-secret-token",
    )
    assert "super-secret-token" not in repr(dto)
    assert "super-secret-token" not in str(dto)
    assert dto.token == "super-secret-token"


async def test_authenticator_runs_constant_time_verify_on_all_failures(
    identity_ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    """Unknown identifier, inactive user and missing-credential paths must
    still run a hasher.verify against a dummy hash so response time does not
    reveal account state (timing side channel)."""

    class RecordingHasher:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def hash(self, password: str) -> str:
            return "hash"

        def verify(self, password: str, encoded: str) -> bool:
            self.calls.append(encoded)
            return False

        def needs_rehash(self, encoded: str) -> bool:
            return False

    hasher = RecordingHasher()
    authenticator = CredentialAuthenticator(uow_factory=uow_factory, hasher=hasher)

    # Unknown identifier still spends a verify.
    assert await authenticator.authenticate_local("ghost", "pw") is None
    assert len(hasher.calls) == 1
    assert hasher.calls[0] == CredentialAuthenticator._DUMMY_HASH

    # Register a user, then ban: inactive path must also verify.
    result = await RegisterLocalUser(identity_ctx)(
        username="tim", email="tim@example.com", password="password-123"
    )
    await BanUser(identity_ctx)(user_id=result.subject.id, reason="x")
    assert await authenticator.authenticate_local("tim", "pw") is None
    assert len(hasher.calls) == 2
    assert hasher.calls[1] == CredentialAuthenticator._DUMMY_HASH

    # Missing credential path verifies too.
    from inc.capabilities.identity.models import IdentityPasswordCredential

    async with uow_factory() as uow:
        await uow.session.execute(
            IdentityPasswordCredential.__table__.delete().where(
                IdentityPasswordCredential.user_id == uuid.UUID(result.subject.id)
            )
        )
        await uow.commit()
    await UnbanUser(identity_ctx)(user_id=result.subject.id)
    assert await authenticator.authenticate_local("tim", "pw") is None
    assert len(hasher.calls) == 3
    assert hasher.calls[2] == CredentialAuthenticator._DUMMY_HASH
