"""Auth, error DTO and request-id tests.

Contract source: context/spec/http-openapi.md §3/§4/§5/§12.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

TEST_AUDIENCE = "aiya-admin"


async def test_me_requires_valid_token(client: Any) -> None:
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "api.unauthorized"
    assert "request_id" in body
    assert "stack" not in str(body)


async def test_legacy_auth_me_route_is_removed(client: Any) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 404


async def test_legacy_points_balance_route_is_removed(client: Any) -> None:
    response = await client.get("/api/v1/points/balance")
    assert response.status_code == 404


async def test_me_returns_principal_and_capabilities(client: Any, admin_token: str) -> None:
    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["subject_id"]
    assert body["display_name"] is None
    assert body["avatar_asset_id"] is None
    assert body["avatar_url"] is None
    assert body["status"] == "active"
    assert body["points"] == {"opened": False, "program_key": "credit", "balance": 0}
    assert "identity.users.read" in body["capabilities"]
    assert "content.write" in body["capabilities"]


async def test_administrator_projection_repairs_stale_capability_rows(
    client: Any, admin_token: str
) -> None:
    """A protected Administrator role remains a live projection of the registry."""

    from sqlalchemy import delete, select

    from inc.capabilities.access.models import AccessRole, AccessRoleCapability

    services = client.app.state.services
    async with services.uow_factory() as uow:
        role_ids = (
            (
                await uow.session.execute(
                    select(AccessRole.id).where(AccessRole.slug == "administrator")
                )
            )
            .scalars()
            .all()
        )
        await uow.session.execute(
            delete(AccessRoleCapability).where(AccessRoleCapability.role_id.in_(role_ids))
        )
        await uow.commit()

    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200, response.text
    assert "points.programs.read" in response.json()["capabilities"]
    assert "content.read" in response.json()["capabilities"]


async def test_me_patch_updates_current_profile(client: Any, admin_token: str) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    avatar_id = str(uuid.uuid4())

    updated = await client.patch(
        "/api/v1/me",
        json={"display_name": "Profile User", "avatar_asset_id": avatar_id},
        headers=headers,
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "Profile User"
    assert updated.json()["avatar_asset_id"] == avatar_id
    assert updated.json()["avatar_url"] is None

    fetched = await client.get("/api/v1/me", headers=headers)
    assert fetched.json()["display_name"] == "Profile User"
    assert fetched.json()["avatar_asset_id"] == avatar_id


async def test_request_id_roundtrip(client: Any, admin_token: str) -> None:
    response = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {admin_token}", "X-Request-ID": "req-123"},
    )
    assert response.headers["x-request-id"] == "req-123"
    bad = await client.get(
        "/api/v1/admin/users",
        headers={"Authorization": "Bearer invalid", "X-Request-ID": "req-456"},
    )
    assert bad.status_code == 401
    assert bad.json()["request_id"] == "req-456"


async def test_forbidden_without_capability(
    client: Any, admin_token: str, uow_factory: Any, clock: Any
) -> None:
    app = client.app
    services = app.state.services
    from inc.capabilities.identity.commands import (
        CommandContext as IdentityCommandContext,
    )
    from inc.capabilities.identity.commands import (
        RegisterLocalUser,
    )

    identity_ctx = IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )
    result = await RegisterLocalUser(identity_ctx)(
        username="nobody", email="nobody@example.com", password="password-123456"
    )
    from tests.api.conftest import _mint_token_for

    token = await _mint_token_for(services, result.subject.id)
    response = await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["code"] == "api.forbidden"


async def test_token_with_wrong_issuer_rejected(client: Any, admin_token: str) -> None:
    app = client.app
    services = app.state.services
    key = await services.keys.ensure_active_key()
    now = datetime.now(UTC)
    claims = {
        "iss": "http://evil",
        "sub": "whatever",
        "aud": [TEST_AUDIENCE],
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
    }
    token = jwt.encode(claims, key.private_key, algorithm="RS256", headers={"kid": key.kid})
    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_expired_token_rejected(client: Any, admin_token: str) -> None:
    app = client.app
    services = app.state.services
    key = await services.keys.ensure_active_key()
    now = datetime.now(UTC)
    claims = {
        "iss": "http://testserver",
        "sub": "x",
        "aud": [TEST_AUDIENCE],
        "exp": int((now - timedelta(minutes=5)).timestamp()),
        "iat": int((now - timedelta(minutes=10)).timestamp()),
    }
    token = jwt.encode(claims, key.private_key, algorithm="RS256", headers={"kid": key.kid})
    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_validation_error_normalized(client: Any, admin_token: str) -> None:
    response = await client.get(
        "/api/v1/admin/users",
        params={"page": 0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "kernel.validation_error"
    assert "request_id" in body


async def test_error_details_never_leak_secrets(client: Any, admin_token: str) -> None:
    # A conflict error whose details carry a secret-looking key must be
    # redacted in the response body.
    payload = {
        "type_name": "post",
        "title": "redact-me",
        "data": {},
    }
    headers = {"Authorization": f"Bearer {admin_token}"}
    first = await client.post("/api/v1/admin/content", json=payload, headers=headers)
    assert first.status_code == 200, first.text

    # Trigger a version conflict; its details must remain opaque.
    second = await client.patch(
        f"/api/v1/admin/content/{first.json()['id']}",
        json={"expected_version": 0, "title": "retry"},
        headers=headers,
    )
    assert second.status_code == 409
    body = second.json()
    assert "code" in body
    assert "message" in body
    # No stack, no provider payload, no raw exception text.
    assert "Traceback" not in str(body)
    assert "<class" not in str(body)


async def test_conflict_maps_to_409(client: Any, admin_token: str) -> None:
    payload = {
        "type_name": "post",
        "title": "dup",
        "data": {},
    }
    headers = {"Authorization": f"Bearer {admin_token}"}
    first = await client.post("/api/v1/admin/content", json=payload, headers=headers)
    assert first.status_code == 200
    second = await client.patch(
        f"/api/v1/admin/content/{first.json()['id']}",
        json={"expected_version": 0, "title": "retry"},
        headers=headers,
    )
    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "content.version_conflict"
    assert "request_id" in body


async def test_unknown_route_error_dto(client: Any, admin_token: str) -> None:
    response = await client.get("/api/v1/admin/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "http.404"


async def test_get_has_no_write_side_effects(
    client: Any, admin_token: str, uow_factory: Any
) -> None:
    from sqlalchemy import func, select

    from inc.kernel.events import OutboxMessage

    async with uow_factory() as uow:
        before = (await uow.session.execute(select(func.count(OutboxMessage.id)))).scalar_one()
    response = await client.get(
        "/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    async with uow_factory() as uow:
        after = (await uow.session.execute(select(func.count(OutboxMessage.id)))).scalar_one()
    assert after == before


async def _sign(services: Any, claims: dict[str, Any], *, kid: str | None = None) -> str:
    key = await services.keys.ensure_active_key()
    return jwt.encode(claims, key.private_key, algorithm="RS256", headers={"kid": kid or key.kid})


async def test_kid_rotation_invalidates_old_tokens(client: Any, admin_token: str) -> None:
    app = client.app
    services = app.state.services
    old_key = await services.keys.ensure_active_key()
    await services.keys.rotate()
    now = datetime.now(UTC)
    import uuid

    claims = {
        "iss": "http://testserver",
        "sub": str(uuid.uuid4()),
        "aud": [TEST_AUDIENCE],
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
        "scope": "openid",
    }
    old_token = jwt.encode(
        claims, old_key.private_key, algorithm="RS256", headers={"kid": old_key.kid}
    )
    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {old_token}"})
    assert response.status_code == 401


async def test_wrong_audience_rejected(client: Any, admin_token: str) -> None:
    app = client.app
    services = app.state.services
    now = datetime.now(UTC)
    import uuid

    claims = {
        "iss": "http://testserver",
        "sub": str(uuid.uuid4()),
        "aud": ["http://testserver", "other-app"],
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
        "scope": "openid",
    }
    token = await _sign(services, claims)
    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_algorithm_confusion_rejected(client: Any, admin_token: str) -> None:
    now = datetime.now(UTC)
    import uuid

    claims = {
        "iss": "http://testserver",
        "sub": str(uuid.uuid4()),
        "aud": [TEST_AUDIENCE],
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
        "scope": "openid",
    }
    # a symmetric key would pass an HMAC verify; RS256 whitelist must reject it
    hs256_token = jwt.encode(claims, "attacker-controlled-symmetric-secret", algorithm="HS256")
    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {hs256_token}"})
    assert response.status_code == 401


async def test_token_without_openid_scope_rejected(client: Any, admin_token: str) -> None:
    app = client.app
    services = app.state.services
    now = datetime.now(UTC)
    import uuid

    claims = {
        "iss": "http://testserver",
        "sub": str(uuid.uuid4()),
        "aud": [TEST_AUDIENCE],
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
        "scope": "email",
    }
    token = await _sign(services, claims)
    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_401_carries_www_authenticate(client: Any) -> None:
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


async def test_invalid_request_id_is_replaced(client: Any, admin_token: str) -> None:
    response = await client.get(
        "/api/v1/me",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Request-ID": "evil\ninjected",
        },
    )
    assert response.status_code == 200
    echoed = response.headers["x-request-id"]
    assert "\n" not in echoed
    assert echoed != "evil\ninjected"


async def test_trailing_newline_request_id_is_replaced(client: Any, admin_token: str) -> None:
    """A trailing newline must not pass the request-id charset gate (the old
    `$`-anchored regex matched just before a trailing newline)."""
    response = await client.get(
        "/api/v1/me",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Request-ID": "req-abc\n",
        },
    )
    assert response.status_code == 200
    echoed = response.headers["x-request-id"]
    assert "\n" not in echoed
    assert echoed != "req-abc\n"


async def test_me_works_without_admin_capabilities(
    client: Any, uow_factory: Any, clock: Any
) -> None:
    app = client.app
    services = app.state.services
    from inc.capabilities.identity.commands import (
        CommandContext as IdentityCommandContext,
    )
    from inc.capabilities.identity.commands import (
        RegisterLocalUser,
    )

    identity_ctx = IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )
    result = await RegisterLocalUser(identity_ctx)(
        username="editor", email="editor@example.com", password="password-123456"
    )
    from tests.api.conftest import _mint_token_for

    token = await _mint_token_for(services, result.subject.id)
    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["capabilities"] == []


def _subject_exists(services: Any) -> Any:
    class _Exists:
        async def exists(self, subject_type: str, subject_id: str) -> bool:
            if subject_type == "identity":
                return await services.identity_queries.get_subject(subject_id) is not None
            return False

    return _Exists()


async def test_writer_without_publish_cannot_publish(
    client: Any, uow_factory: Any, clock: Any
) -> None:
    """A user with content.write but without content.publish gets 403 on
    publish from both the router gate and the command's own check."""

    app = client.app
    services = app.state.services
    from inc.capabilities.access.commands import (
        AssignRoleToSubject,
        CreateRole,
    )
    from inc.capabilities.access.commands import (
        CommandContext as AccessCommandContext,
    )
    from inc.capabilities.identity.commands import (
        CommandContext as IdentityCommandContext,
    )
    from inc.capabilities.identity.commands import (
        RegisterLocalUser,
    )

    identity_ctx = IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )
    result = await RegisterLocalUser(identity_ctx)(
        username="writer", email="writer@example.com", password="password-123456"
    )
    access_ctx = AccessCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=services.outbox,
        permissions=services.permission_registry,
        subject_exists=_subject_exists(services),
        audit_actor_id="system",
        audit_trace_id="test",
    )
    role = await CreateRole(access_ctx)(name="writer", slug="writer")
    await AssignRoleToSubject(access_ctx)(
        subject_type="identity", subject_id=result.subject.id, role_id=role.id
    )
    # grant the role only content.write
    from inc.capabilities.access.models import AccessRoleCapability

    async with uow_factory() as uow:
        uow.session.add(
            AccessRoleCapability(role_id=uuid.UUID(role.id), capability_key="content.write")
        )
        await uow.commit()

    from tests.api.conftest import _mint_token_for

    token = await _mint_token_for(services, result.subject.id)
    created = await client.post(
        "/api/v1/admin/content",
        json={
            "type_name": "post",
            "title": "writer post",
            "data": {},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 200, created.text
    content_id = created.json()["id"]
    denied = await client.post(
        f"/api/v1/admin/content/{content_id}/publish",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "api.forbidden"


def _identity_ctx(uow_factory: Any, clock: Any, services: Any) -> Any:
    from inc.capabilities.identity.commands import CommandContext as IdentityCommandContext

    return IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )


async def test_password_reset_request_is_public_and_enumeration_safe(
    client: Any, uow_factory: Any, clock: Any
) -> None:
    from inc.capabilities.identity.commands import RegisterLocalUser

    services = client.app.state.services
    ghost = await client.post(
        "/api/v1/auth/password-reset/request", json={"identifier": "ghost@example.com"}
    )
    assert ghost.status_code == 202

    await RegisterLocalUser(_identity_ctx(uow_factory, clock, services))(
        username="resetme", email="resetme@example.com", password="password-123456"
    )
    known = await client.post(
        "/api/v1/auth/password-reset/request", json={"identifier": "ResetMe@Example.com"}
    )
    assert known.status_code == 202
    # equivalent external responses; the token never appears in any body
    assert known.json() == ghost.json()
    assert "token" not in str(known.json()).lower()


async def test_password_reset_request_is_limited_per_source(client: Any) -> None:
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/password-reset/request", json={"identifier": "ghost@example.com"}
        )
        assert response.status_code == 202

    limited = await client.post(
        "/api/v1/auth/password-reset/request", json={"identifier": "ghost@example.com"}
    )
    assert limited.status_code == 429
    assert limited.json()["code"] == "auth.password_reset_rate_limited"


async def test_password_reset_confirm_rotates_credential_and_blocks_replay(
    client: Any, uow_factory: Any, clock: Any
) -> None:
    from inc.capabilities.identity.commands import RegisterLocalUser, RequestPasswordReset
    from inc.capabilities.identity.queries import CredentialAuthenticator
    from inc.kernel.security import Argon2PasswordHasher

    services = client.app.state.services
    identity_ctx = _identity_ctx(uow_factory, clock, services)
    result = await RegisterLocalUser(identity_ctx)(
        username="resetflow", email="resetflow@example.com", password="old-password-1"
    )
    challenge = await RequestPasswordReset(identity_ctx)(identifier="resetflow@example.com")
    assert challenge is not None and challenge.token is not None

    confirm = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": challenge.token, "new_password": "new-password-2"},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["id"] == result.subject.id

    replay = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": challenge.token, "new_password": "new-password-2"},
    )
    assert replay.status_code == 422
    assert replay.json()["code"] == "identity.challenge_consumed"

    authenticator = CredentialAuthenticator(uow_factory=uow_factory, hasher=Argon2PasswordHasher())
    assert await authenticator.authenticate_local("resetflow", "old-password-1") is None
    assert await authenticator.authenticate_local("resetflow", "new-password-2") is not None


async def test_password_reset_confirm_rejects_bad_token_and_weak_password(client: Any) -> None:
    bad = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "guessed-token", "new_password": "new-password-2"},
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "identity.challenge_invalid"

    weak = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "guessed-token", "new_password": "short"},
    )
    assert weak.status_code == 422
    assert weak.json()["code"] == "kernel.validation_error"


async def test_register_is_public_and_normalizes(client: Any, uow_factory: Any) -> None:
    from inc.capabilities.identity.queries import CredentialAuthenticator
    from inc.kernel.security import Argon2PasswordHasher

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "NewUser",
            "email": "NewUser@Example.COM",
            "password": "password-123456",
            "display_name": "New User",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["username"] == "NewUser"
    assert body["email_verified"] is False
    assert "token" not in str(body).lower()

    authenticator = CredentialAuthenticator(uow_factory=uow_factory, hasher=Argon2PasswordHasher())
    assert await authenticator.authenticate_local("newuser", "password-123456") is not None

    # API registration attaches the protected baseline User role.
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    token = await _mint_token_for(services, body["id"])
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert {
        "community.discussions.create",
        "community.discussions.reply",
        "community.discussions.edit_own",
        "comments.submit",
    } <= set(me.json()["capabilities"])


async def test_register_fails_closed_when_default_role_seed_is_missing(
    client: Any, uow_factory: Any
) -> None:
    from sqlalchemy import delete, select

    from inc.capabilities.access.models import AccessRole, AccessRoleCapability
    from inc.capabilities.identity.models import IdentityUser

    async with uow_factory() as uow:
        role_id = (
            await uow.session.execute(select(AccessRole.id).where(AccessRole.slug == "user"))
        ).scalar_one()
        await uow.session.execute(
            delete(AccessRoleCapability).where(AccessRoleCapability.role_id == role_id)
        )
        await uow.session.execute(delete(AccessRole).where(AccessRole.id == role_id))
        await uow.commit()

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "missing-role",
            "email": "missing-role@example.com",
            "password": "password-123456",
        },
    )
    assert response.status_code == 503
    assert response.json()["code"] == "auth.registration_unavailable"

    async with uow_factory() as uow:
        created = (
            await uow.session.execute(
                select(IdentityUser.id).where(IdentityUser.username_normalized == "missing-role")
            )
        ).scalar_one_or_none()
    assert created is None


async def test_register_conflict_and_weak_password_are_stable_errors(client: Any) -> None:
    first = await client.post(
        "/api/v1/auth/register",
        json={"username": "dup", "email": "dup@example.com", "password": "password-123456"},
    )
    assert first.status_code == 200, first.text

    conflict = await client.post(
        "/api/v1/auth/register",
        json={"username": "DUP", "email": "other@example.com", "password": "password-123456"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "identity.duplicate_identifier"

    weak = await client.post(
        "/api/v1/auth/register",
        json={"username": "weakpw", "email": "weakpw@example.com", "password": "short"},
    )
    assert weak.status_code == 422
    assert weak.json()["code"] == "kernel.validation_error"


async def test_verify_email_consumes_one_time_token(
    client: Any, uow_factory: Any, clock: Any
) -> None:
    from inc.capabilities.identity.commands import RegisterLocalUser

    services = client.app.state.services
    result = await RegisterLocalUser(_identity_ctx(uow_factory, clock, services))(
        username="verifyme",
        email="verifyme@example.com",
        password="password-123456",
        issue_email_challenge=True,
    )
    assert result.challenge is not None and result.challenge.token is not None

    verified = await client.post(
        "/api/v1/auth/verify-email", json={"token": result.challenge.token}
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["email_verified"] is True

    replay = await client.post("/api/v1/auth/verify-email", json={"token": result.challenge.token})
    assert replay.status_code == 422
    assert replay.json()["code"] == "identity.challenge_consumed"

    bad = await client.post("/api/v1/auth/verify-email", json={"token": "guessed-token"})
    assert bad.status_code == 422
    assert bad.json()["code"] == "identity.challenge_invalid"


async def test_grants_requires_valid_token(client: Any) -> None:
    response = await client.get("/api/v1/auth/grants")
    assert response.status_code == 401
    assert response.json()["code"] == "api.unauthorized"


async def test_grants_are_user_scoped_and_revoke_without_admin_capability(
    client: Any, uow_factory: Any, clock: Any
) -> None:
    services = client.app.state.services
    from inc.capabilities.identity.commands import RegisterLocalUser

    result = await RegisterLocalUser(_identity_ctx(uow_factory, clock, services))(
        username="grant-user", email="grant-user@example.com", password="password-123456"
    )
    from tests.api.conftest import _mint_token_for

    token = await _mint_token_for(services, result.subject.id)

    from inc.capabilities.oidc_provider.clients import ClientCommandContext, RegisterClient
    from inc.capabilities.oidc_provider.models import OidcGrantConsent, StringList

    await RegisterClient(
        ClientCommandContext(
            uow_factory=uow_factory,
            clock=clock,
            outbox=services.outbox,
            audit_actor_id="system",
            audit_trace_id="test",
        )
    )(
        name="Grant App",
        client_type="public",
        redirect_uris=["http://127.0.0.1:3000/grant-callback"],
        client_id="grant-app",
    )
    async with uow_factory() as uow:
        uow.session.add(
            OidcGrantConsent(
                subject_id=result.subject.id,
                client_id="grant-app",
                scopes=StringList(items=["openid", "profile"]),
                audiences=StringList(items=["api"]),
                granted_at=clock.utc_now(),
            )
        )
        await uow.commit()

    listed = await client.get("/api/v1/auth/grants", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200, listed.text
    assert listed.json() == [
        {
            "client_id": "grant-app",
            "client_name": "Grant App",
            "scopes": ["openid", "profile"],
            "audiences": ["api"],
            "granted_at": "2026-01-01T00:00:00Z",
        }
    ]

    revoked = await client.delete(
        "/api/v1/auth/grants/grant-app", headers={"Authorization": f"Bearer {token}"}
    )
    assert revoked.status_code == 204
    assert (
        await client.get("/api/v1/auth/grants", headers={"Authorization": f"Bearer {token}"})
    ).json() == []
