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
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "api.unauthorized"
    assert "request_id" in body
    assert "stack" not in str(body)


async def test_me_returns_principal_and_capabilities(client: Any, admin_token: str) -> None:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["subject_id"]
    assert body["status"] == "active"
    assert "identity.users.read" in body["capabilities"]
    assert "content.write" in body["capabilities"]


async def test_request_id_roundtrip(client: Any, admin_token: str) -> None:
    response = await client.get(
        "/api/v1/auth/me",
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
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
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
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
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


async def test_conflict_maps_to_409(client: Any, admin_token: str) -> None:
    payload = {
        "type_name": "post",
        "title": "dup",
        "slug": "same-slug",
        "data": {"summary": "s"},
    }
    headers = {"Authorization": f"Bearer {admin_token}"}
    first = await client.post("/api/v1/admin/content", json=payload, headers=headers)
    assert first.status_code == 200
    second = await client.post("/api/v1/admin/content", json=payload, headers=headers)
    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "content.duplicate_slug"
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
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
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
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
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
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {hs256_token}"}
    )
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
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_401_carries_www_authenticate(client: Any) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


async def test_invalid_request_id_is_replaced(client: Any, admin_token: str) -> None:
    response = await client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Request-ID": "evil\ninjected",
        },
    )
    assert response.status_code == 200
    echoed = response.headers["x-request-id"]
    assert "\n" not in echoed
    assert echoed != "evil\ninjected"


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
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
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
            "slug": "writer-post",
            "data": {"summary": "s"},
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
