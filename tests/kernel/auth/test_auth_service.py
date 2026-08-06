"""Auth service integration tests (M1.8 / auth.md)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inc.kernel.auth import (
    AUTH_001,
    AUTH_003,
    AUTH_004,
    AUTH_005,
    AUTH_006,
    AUTH_007,
    AUTH_008,
    AUTH_009,
    AUTH_010,
    AuthRegistrationPolicy,
    AuthService,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from inc.kernel.auth.uow import AuthUnitOfWork
from inc.kernel.cache import MemoryCache
from inc.kernel.db import UoWExecutor
from inc.kernel.errors import AppError
from inc.kernel.events import Event, fresh_event_bus
from inc.kernel.identity import IdentityService, IdentityUnitOfWork
from inc.kernel.rbac import RBACUnitOfWork, seed_rbac
from inc.kernel.security import TokenService


def _service(
    session_factory: async_sessionmaker[AsyncSession],
    auth_settings,
) -> tuple[AuthService, object]:
    bus = fresh_event_bus()
    service = AuthService(
        UoWExecutor(lambda: AuthUnitOfWork(session_factory)),
        TokenService(auth_settings),
        MemoryCache(),
        event_bus=bus,
    )
    return service, bus


async def test_register_login_refresh_logout_chain(session_factory, auth_settings) -> None:
    service, bus = _service(session_factory, auth_settings)
    registered: list[Event] = []

    async def collect(event: Event) -> None:
        registered.append(event)

    bus.subscribe("user.registered", collect)
    bus.freeze()

    user = await service.register(
        RegisterRequest(
            username="Alice",
            email="alice@example.com",
            password="correct horse battery staple",
            display_name="Alice",
        )
    )
    await bus.wait_idle()
    assert user.username == "alice"
    assert len(registered) == 1

    pair = await service.login(
        LoginRequest(identifier="ALICE", password="correct horse battery staple"),
        ip="127.0.0.1",
        user_agent="pytest",
    )
    claims = service.token_service.verify_access(pair.access_token)
    assert claims.sub == user.id

    rotated = await service.refresh(pair.refresh_token)
    assert rotated.refresh_token != pair.refresh_token
    with pytest.raises(AppError) as replay:
        await service.refresh(pair.refresh_token)
    assert replay.value.code == AUTH_003

    await service.logout(rotated.refresh_token)
    with pytest.raises(AppError) as logged_out:
        await service.refresh(rotated.refresh_token)
    assert logged_out.value.code == AUTH_003


async def test_register_duplicate_email_and_username_map_stable_errors(
    session_factory, auth_settings
) -> None:
    service, _ = _service(session_factory, auth_settings)
    await service.register(
        RegisterRequest(username="alice", email="alice@example.com", password="password")
    )
    with pytest.raises(AppError) as email_error:
        await service.register(
            RegisterRequest(username="other", email="alice@example.com", password="password")
        )
    assert email_error.value.code == AUTH_004
    with pytest.raises(AppError) as username_error:
        await service.register(
            RegisterRequest(username="alice", email="other@example.com", password="password")
        )
    assert username_error.value.code == AUTH_005


async def test_bootstrap_admin_creates_admin_role_in_one_auth_transaction(
    session_factory, auth_settings
) -> None:
    await seed_rbac(UoWExecutor(lambda: RBACUnitOfWork(session_factory)))
    service, _ = _service(session_factory, auth_settings)

    user = await service.bootstrap_admin(
        RegisterRequest(username="root", email="root@example.com", password="password")
    )

    async with AuthUnitOfWork(session_factory) as uow:
        roles = await uow.auth.role_names(user.id)
        capabilities = await uow.auth.capabilities(user.id)
    assert roles == frozenset({"admin"})
    assert "role:assign" in capabilities


async def test_login_failures_rate_limit_and_unknown_user_are_opaque(
    session_factory, auth_settings
) -> None:
    service, _ = _service(session_factory, auth_settings)
    await service.register(
        RegisterRequest(username="alice", email="alice@example.com", password="password")
    )
    for _ in range(4):
        with pytest.raises(AppError) as failure:
            await service.login(
                LoginRequest(identifier="alice", password="wrong"), ip="1.2.3.4", user_agent="test"
            )
        assert failure.value.code == AUTH_001
    with pytest.raises(AppError) as limited:
        await service.login(
            LoginRequest(identifier="alice", password="wrong"), ip="1.2.3.4", user_agent="test"
        )
    assert limited.value.code == AUTH_007
    with pytest.raises(AppError) as unknown:
        await service.login(
            LoginRequest(identifier="nobody", password="wrong"), ip="8.8.8.8", user_agent="test"
        )
    assert unknown.value.code == AUTH_001


async def test_banned_user_cannot_login(session_factory, auth_settings) -> None:
    service, _ = _service(session_factory, auth_settings)
    user = await service.register(
        RegisterRequest(username="alice", email="alice@example.com", password="password")
    )
    identity = IdentityService(UoWExecutor(lambda: IdentityUnitOfWork(session_factory)))
    await identity.ban(user.id)

    with pytest.raises(AppError) as banned:
        await service.login(
            LoginRequest(identifier="alice", password="password"), ip="127.0.0.1", user_agent="test"
        )
    assert banned.value.code == AUTH_006


async def test_refresh_rotation_creates_exactly_one_replacement(
    session_factory, auth_settings
) -> None:
    service, _ = _service(session_factory, auth_settings)
    user = await service.register(
        RegisterRequest(username="rotate", email="rotate@example.com", password="password")
    )
    pair = await service.login(
        LoginRequest(identifier="rotate", password="password"), ip="127.0.0.1", user_agent="test"
    )

    rotated = await service.refresh(pair.refresh_token)
    async with AuthUnitOfWork(session_factory) as uow:
        rows = await uow.refresh_tokens.list_for_user(user.id)
        active_count = sum(row.revoked_at is None for row in rows)

    assert len(rows) == 2
    assert active_count == 1
    assert rotated.refresh_token != pair.refresh_token


async def test_registration_policy_and_password_reset_are_enforced(
    session_factory, auth_settings
) -> None:
    service, _ = _service(session_factory, auth_settings)
    with pytest.raises(AppError) as closed:
        await service.register(
            RegisterRequest(username="closed", email="closed@example.com", password="password"),
            AuthRegistrationPolicy(registration_open=False),
        )
    assert closed.value.code == AUTH_008

    user = await service.register(
        RegisterRequest(username="reset", email="reset@example.com", password="password")
    )
    delivery = await service.request_password_reset(
        ForgotPasswordRequest(email="reset@example.com")
    )
    assert delivery is not None
    assert delivery.email == user.email
    await service.reset_password(
        ResetPasswordRequest(token=delivery.token, password="new-password")
    )
    with pytest.raises(AppError) as old_token:
        await service.reset_password(
            ResetPasswordRequest(token=delivery.token, password="third-password")
        )
    assert old_token.value.code == AUTH_009

    for _ in range(5):
        await service.request_password_reset(
            ForgotPasswordRequest(email="reset@example.com"), ip="203.0.113.9"
        )
    with pytest.raises(AppError) as limited:
        await service.request_password_reset(
            ForgotPasswordRequest(email="reset@example.com"), ip="203.0.113.9"
        )
    assert limited.value.code == AUTH_010
