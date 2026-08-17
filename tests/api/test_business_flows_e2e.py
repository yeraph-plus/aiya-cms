"""End-to-end business flow tests over the full cms manifest.

Contract source: context/spec/http-openapi.md §2, context/spec/features.md,
context/spec/capabilities/identity.md, access.md, points.md,
oidc-provider.md.

One user walks the whole lifecycle over HTTP: register, verify email,
assign role, OIDC login, credit points (check-in + admin adjust), debit
points (admin adjust), logout, password reset, ban and unban.

One-time challenge tokens are delivered out-of-band by design; the test
holds them as the in-process caller (the notification workflow's stand-in),
exactly like tests/api/test_auth_http.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.api.conftest import TEST_AUDIENCE

REDIRECT_URI = "http://127.0.0.1:3000/cb"
LOGOUT_REDIRECT = "http://127.0.0.1:3000/logged-out"
CLIENT_ID = "e2e-spa"
SCOPES = "openid profile email"


@pytest.fixture
async def program(uow_factory: Any) -> None:
    from inc.capabilities.points.models import PointsProgram

    async with uow_factory() as uow:
        uow.session.add(
            PointsProgram(
                program_key="credit", display_name="Credit", unit="points", status="active"
            )
        )
        await uow.commit()


@pytest.fixture
def clock() -> Any:
    """Real-time clock: OIDC tokens are validated by PyJWT against the wall
    clock (inc/api/http/context.py), so issuance must happen at real 'now'."""
    from datetime import UTC, datetime

    from inc.kernel.time.fake import FakeClock

    return FakeClock(datetime.now(UTC))


def _identity_ctx(uow_factory: Any, clock: Any, services: Any) -> Any:
    from inc.capabilities.identity.commands import (
        CommandContext as IdentityCommandContext,
    )

    return IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )


async def _register_with_challenge(
    client: Any, uow_factory: Any, clock: Any, username: str
) -> tuple[Any, str]:
    """Register a user; the email-verification token is delivered out-of-band
    (the notification workflow's stand-in is the in-process caller)."""
    from inc.capabilities.identity.commands import RegisterLocalUser

    services = client.app.state.services
    result = await RegisterLocalUser(_identity_ctx(uow_factory, clock, services))(
        username=username,
        email=f"{username}@example.com",
        password="password-123456",
        issue_email_challenge=True,
    )
    assert result.challenge is not None and result.challenge.token is not None
    return result.subject, result.challenge.token


async def _register_oidc_client(services: Any, uow_factory: Any, clock: Any) -> None:
    from inc.capabilities.oidc_provider.clients import (
        ClientCommandContext,
        RegisterClient,
    )

    await RegisterClient(
        ClientCommandContext(
            uow_factory=uow_factory,
            clock=clock,
            outbox=services.outbox,
            audit_actor_id="system",
            audit_trace_id="test",
        )
    )(
        name="E2E SPA",
        client_type="public",
        redirect_uris=[REDIRECT_URI],
        post_logout_redirect_uris=[LOGOUT_REDIRECT],
        allowed_scopes=["openid", "profile", "email"],
        allowed_audiences=[TEST_AUDIENCE],
        client_id=CLIENT_ID,
        allow_refresh=False,
    )


def _pkce() -> tuple[str, str]:
    import base64
    import hashlib
    import secrets

    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def _authorize_params(challenge: str) -> dict[str, str]:
    return {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": "st-e2e",
        "nonce": "n-e2e",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }


async def _oidc_login(client: Any, username: str, password: str) -> tuple[str, str]:
    """Full browser OIDC code + PKCE login; returns (access_token, id_token)."""
    verifier, challenge = _pkce()
    params = _authorize_params(challenge)
    visit = await client.get("/oidc/authorize", params=params)
    assert visit.status_code == 200
    login = await client.post(
        "/oidc/login", data={"username": username, "password": password, **params}
    )
    assert login.status_code == 302, login.text
    auth = await client.get("/oidc/authorize", params=params)
    assert auth.status_code == 302, auth.text
    location = auth.headers["location"]
    assert "state=st-e2e" in location
    code = location.split("code=")[1].split("&")[0]
    token = await client.post(
        "/oidc/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200, token.text
    body = token.json()
    assert body["access_token"] and body["id_token"]
    return body["access_token"], body["id_token"]


def _adjust_body(*, subject_id: str, amount: int, idempotency_key: str) -> dict[str, Any]:
    return {
        "subject_type": "identity",
        "subject_id": subject_id,
        "program_key": "credit",
        "amount": amount,
        "reason": "e2e adjustment",
        "idempotency_key": idempotency_key,
    }


async def test_public_register_endpoint(client: Any) -> None:
    """The public register endpoint works end to end and never leaks tokens."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "Carol",
            "email": "Carol@Example.com",
            "password": "password-123456",
            "display_name": "Carol C",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["username"] == "Carol"
    assert body["email_verified"] is False
    assert "token" not in str(body).lower()


async def test_full_business_flow(
    client: Any, admin_token: str, uow_factory: Any, clock: Any, program: None
) -> None:
    services = client.app.state.services

    # 1. 注册 + 邮箱验证（challenge token 带外投递）
    subject, email_token = await _register_with_challenge(client, uow_factory, clock, "alice")
    verify = await client.post("/api/v1/auth/verify-email", json={"token": email_token})
    assert verify.status_code == 200, verify.text
    assert verify.json()["email_verified"] is True

    # 2. 分配角色：管理员建角色、绑定权限、指派给 alice
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    role = await client.post(
        "/api/v1/admin/roles",
        json={"name": "Flow editor", "slug": "flow-editor"},
        headers=admin_headers,
    )
    assert role.status_code == 200, role.text
    role_id = role.json()["id"]

    from inc.capabilities.access.commands import (
        CommandContext as AccessCommandContext,
    )
    from inc.capabilities.access.commands import (
        ReplaceRoleCapabilities,
    )
    from tests.api.conftest import _always_exists

    # binding capability keys to a role has no HTTP surface (test_access_http
    # does the same); the assignment itself is exercised over HTTP.
    await ReplaceRoleCapabilities(
        AccessCommandContext(
            uow_factory=uow_factory,
            clock=clock,
            outbox=services.outbox,
            permissions=services.permission_registry,
            subject_exists=_always_exists(),
            audit_actor_id="system",
            audit_trace_id="test",
        )
    )(role_id=role_id, capability_keys=("content.write", "identity.users.read"))
    assigned = await client.post(
        f"/api/v1/admin/roles/{role_id}/assign",
        json={"subject_type": "identity", "subject_id": subject.id},
        headers=admin_headers,
    )
    assert assigned.status_code == 200, assigned.text

    # 3. 登录：OIDC 授权码 + PKCE，/me 反映角色能力
    await _register_oidc_client(services, uow_factory, clock)
    access_token, id_token = await _oidc_login(client, "alice", "password-123456")
    headers = {"Authorization": f"Bearer {access_token}"}
    me = await client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200, me.text
    assert {"content.write", "identity.users.read"} <= set(me.json()["capabilities"])

    # 4. 增加积分：签到 +10
    checkin = await client.post("/api/v1/check-in", headers=headers)
    assert checkin.status_code == 200, checkin.text
    assert checkin.json()["status"] == "rewarded"
    assert checkin.json()["balance"] == 10

    # 5. 增加积分：管理员正向调整 +50 → 60
    credit = await client.post(
        "/api/v1/admin/points/adjust",
        json=_adjust_body(subject_id=subject.id, amount=50, idempotency_key="e2e-credit"),
        headers=admin_headers,
    )
    assert credit.status_code == 200, credit.text

    # 6. 扣减积分：管理员负向调整 -20 → 40
    debit = await client.post(
        "/api/v1/admin/points/adjust",
        json=_adjust_body(subject_id=subject.id, amount=-20, idempotency_key="e2e-debit"),
        headers=admin_headers,
    )
    assert debit.status_code == 200, debit.text

    me_after_points = await client.get("/api/v1/me", headers=headers)
    assert me_after_points.status_code == 200
    assert me_after_points.json()["points"]["balance"] == 40

    # 7. 登出：RP-Initiated Logout，精确 post-logout 重定向并撤销 OIDC 会话
    logout = await client.get(
        "/oidc/logout",
        params={
            "id_token_hint": id_token,
            "post_logout_redirect_uri": LOGOUT_REDIRECT,
        },
    )
    assert logout.status_code == 302
    assert logout.headers["location"] == LOGOUT_REDIRECT

    from sqlalchemy import select

    from inc.capabilities.oidc_provider.models import OidcSession

    async with uow_factory() as uow:
        sessions = (await uow.session.execute(select(OidcSession))).scalars().all()
        assert sessions and all(s.revoked_at is not None for s in sessions)

    # 8. 密码找回：请求(202 防枚举) → 带外 token → confirm → 旧密码失效、新密码可登录
    requested = await client.post(
        "/api/v1/auth/password-reset/request", json={"identifier": "alice@example.com"}
    )
    assert requested.status_code == 202

    from inc.capabilities.identity.commands import RequestPasswordReset

    challenge = await RequestPasswordReset(_identity_ctx(uow_factory, clock, services))(
        identifier="alice@example.com"
    )
    assert challenge is not None and challenge.token is not None
    confirm = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": challenge.token, "new_password": "new-password-9"},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["id"] == subject.id

    verifier2, challenge2 = _pkce()
    params2 = _authorize_params(challenge2)
    await client.get("/oidc/authorize", params=params2)
    stale = await client.post(
        "/oidc/login",
        data={"username": "alice", "password": "password-123456", **params2},
    )
    assert stale.status_code == 401
    await _oidc_login(client, "alice", "new-password-9")

    # 9. 封禁：banned 后同一 Bearer 立即失效
    banned = await client.post(
        f"/api/v1/admin/users/{subject.id}/ban",
        json={"reason": "spam"},
        headers=admin_headers,
    )
    assert banned.status_code == 200
    assert banned.json()["status"] == "banned"
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401

    # 10. 解封：解封后同一 Bearer 恢复
    unbanned = await client.post(f"/api/v1/admin/users/{subject.id}/unban", headers=admin_headers)
    assert unbanned.status_code == 200, unbanned.text
    assert unbanned.json()["status"] == "active"
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 200
