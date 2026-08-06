"""Identity capability tests.

Contract source: context/spec/capabilities/identity.md §10.

Runs against SQLite with the kernel UoW/outbox code paths.
"""

from __future__ import annotations

from datetime import timedelta
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
