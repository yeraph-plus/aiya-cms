"""Authentication notification delivery policy contracts."""

import pytest

from inc.api.http.routers_auth import PASSWORD_RESET_REQUEST_LIMIT
from inc.capabilities.notification.auth import (
    AUTH_CHALLENGE_DELIVERY_MAX_ATTEMPTS,
    AUTH_NOTIFICATION_SPECS,
)
from inc.capabilities.notification.specs import (
    NOTIFICATION_DELIVERY_MAX_ATTEMPTS,
    NotificationSpecRegistry,
)
from inc.kernel.errors import KernelError
from inc.kernel.security import SensitiveValueProtector


def test_identity_challenge_delivery_budget_is_explicit_and_aligned() -> None:
    assert AUTH_CHALLENGE_DELIVERY_MAX_ATTEMPTS == NOTIFICATION_DELIVERY_MAX_ATTEMPTS
    assert AUTH_CHALLENGE_DELIVERY_MAX_ATTEMPTS == PASSWORD_RESET_REQUEST_LIMIT == 5
    assert {spec.delivery_policy.max_attempts for spec in AUTH_NOTIFICATION_SPECS} == {
        AUTH_CHALLENGE_DELIVERY_MAX_ATTEMPTS
    }


def test_release_registry_allows_only_internal_identity_triggers() -> None:
    registry = NotificationSpecRegistry()
    for spec in AUTH_NOTIFICATION_SPECS:
        registry.register(spec)
    assert {spec.trigger_name for spec in registry.specs()} == {
        "identity.email_verification",
        "identity.password_reset",
    }
    with pytest.raises(KernelError) as excinfo:
        registry.require_trigger("identity.unknown")
    assert excinfo.value.code == "notification.unknown_trigger"


def test_sensitive_challenge_values_are_encrypted_and_scrubbable() -> None:
    protector = SensitiveValueProtector.from_secret("admin-session-secret-for-tests")
    protected = protector.protect_mapping(
        {"username": "alice", "token": "challenge-token", "expires_at": "2026-01-01T00:00:00Z"}
    )

    assert protected["token"] != "challenge-token"
    assert "challenge-token" not in str(protected)
    assert protector.reveal_mapping(protected)["token"] == "challenge-token"
    assert "token" not in protector.scrub_mapping(protected)
