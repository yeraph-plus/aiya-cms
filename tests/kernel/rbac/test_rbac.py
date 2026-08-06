"""RBAC contract tests (M1.6 / ADR-0019)."""

from uuid import uuid4

import pytest
from starlette.requests import Request

from inc.kernel.errors import AppError, clear_registry, register_error_codes
from inc.kernel.rbac import (
    ALL_CAPABILITIES,
    RBAC_CODES,
    ROLE_SEEDS,
    CapabilityChecker,
    PolicyContext,
    Principal,
    capability_registry,
    require_capability,
    validate_capability_registry,
)


@pytest.fixture(autouse=True)
def fresh_registries() -> None:
    clear_registry()
    register_error_codes(*RBAC_CODES)
    capability_registry.reset()
    capability_registry.register_many(ALL_CAPABILITIES)
    yield


def test_anonymous_and_system_bot_rules() -> None:
    checker = CapabilityChecker()
    anonymous = Principal.anonymous()
    bot = Principal.system_bot(capabilities={"anything"})

    assert not checker.check(anonymous, "user:read_any")
    assert checker.check(bot, "user:read_any", None)


def test_owner_policy_and_any_capability() -> None:
    checker = CapabilityChecker()
    principal = Principal(
        id=uuid4(),
        username="alice",
        roles=frozenset({"member"}),
        capabilities=frozenset({"content:update_own"}),
    )
    context = PolicyContext(resource_owner_id=principal.id)

    assert checker.check(principal, "content:update_own", context)
    assert not checker.check(
        principal, "content:update_own", PolicyContext(resource_owner_id=uuid4())
    )
    elevated = principal.model_copy(update={"capabilities": frozenset({"content:update_any"})})
    assert checker.check(elevated, "content:update_own", PolicyContext(resource_owner_id=uuid4()))


def test_any_capabilities_do_not_cross_operation_boundaries() -> None:
    checker = CapabilityChecker()
    principal = Principal(
        id=uuid4(),
        username="moderator",
        capabilities=frozenset({"content:delete_any"}),
    )

    assert not checker.check(
        principal, "content:update_own", PolicyContext(resource_owner_id=uuid4())
    )
    assert not checker.check(principal, "content:publish", PolicyContext(resource_owner_id=uuid4()))


def test_publish_any_policy_requires_update_any() -> None:
    checker = CapabilityChecker()
    principal = Principal(
        id=uuid4(),
        username="editor",
        capabilities=frozenset({"content:update_any"}),
    )

    assert checker.check(principal, "content:publish", PolicyContext(resource_owner_id=uuid4()))


async def test_capability_dependency_preserves_authentication_errors() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/"})
    request.state.auth_error = AppError(RBAC_CODES[0])
    dependency = require_capability("user:read_any")

    with pytest.raises(AppError) as excinfo:
        await dependency(request, Principal.anonymous())

    assert excinfo.value.code == RBAC_CODES[0]


def test_unknown_capability_fails_fast_and_dependency_rejects() -> None:
    with pytest.raises(RuntimeError):
        validate_capability_registry(["unknown:operation"])

    with pytest.raises(AppError) as excinfo:
        require_capability("unknown:operation")
    assert excinfo.value.code.code == "RBAC_003"


def test_seed_shape_is_explicit_and_system_bot_is_not_a_db_role() -> None:
    assert {seed.name for seed in ROLE_SEEDS} >= {
        "reader",
        "member",
        "editor",
        "moderator",
        "admin",
    }
    assert all(seed.name != "system-bot" for seed in ROLE_SEEDS)
