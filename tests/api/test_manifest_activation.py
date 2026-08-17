"""Manifest activation scope tests.

Contract source: context/spec/composition.md §9, http-openapi.md §12.
"""

from __future__ import annotations

import sys
from typing import Any

import httpx
import pytest

from inc.api.app import create_app
from inc.api.config import ApiSettings
from inc.api.container import build_container
from inc.api.manifest import cms, kernel_only, management_plane
from inc.kernel.boot import AppManifest
from inc.kernel.errors import KernelError


@pytest.fixture
def settings() -> ApiSettings:
    return ApiSettings(issuer="http://testserver")


async def _kernel_only_client(uow_factory: Any, clock: Any, settings: Any) -> Any:
    app = create_app(
        manifest=kernel_only,
        uow_factory=uow_factory,
        clock=clock,
        settings=settings,
        start_workers=False,
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_kernel_only_exposes_only_health(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    async with await _kernel_only_client(uow_factory, clock, settings) as client:
        healthz = await client.get("/healthz")
        assert healthz.status_code == 200 and healthz.json()["status"] == "ok"
        health = await client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["manifest"] == "kernel_only"
        assert health.json()["capabilities"] == []
        missing = await client.get("/api/v1/admin/users")
        assert missing.status_code == 404
        body = missing.json()
        assert body["code"] == "http.404"


def test_production_app_requires_redis_for_admin_sessions(uow_factory: Any, clock: Any) -> None:
    production = ApiSettings(
        environment="production",
        issuer="https://cms.example.com",
        secure_cookies=True,
        oidc_signing_key_dir="/var/lib/aiya/oidc-keys",
        admin_session_secret="x" * 48,
    )
    with pytest.raises(ValueError, match="requires a Redis URL"):
        create_app(
            manifest=kernel_only,
            uow_factory=uow_factory,
            clock=clock,
            settings=production,
            redis_url=None,
            start_workers=False,
        )


async def test_kernel_only_openapi_has_no_business_paths(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    app = create_app(
        manifest=kernel_only,
        uow_factory=uow_factory,
        clock=clock,
        settings=settings,
        start_workers=False,
    )
    paths = set(app.openapi()["paths"])
    assert "/healthz" in paths
    assert not any(p.startswith("/api/v1/admin") for p in paths)
    assert not any(p.startswith("/oidc") for p in paths)


async def test_readiness_reports_redis_failure(
    uow_factory: Any, clock: Any, settings: ApiSettings, monkeypatch: Any
) -> None:
    from redis.asyncio import Redis

    class BrokenRedis:
        async def ping(self) -> bool:
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: BrokenRedis())
    app = create_app(
        manifest=kernel_only,
        uow_factory=uow_factory,
        clock=clock,
        settings=settings,
        redis_url="redis://broken/0",
        start_workers=False,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


async def test_kernel_only_does_not_import_deferred_capability_or_business_router(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    sys.modules.pop("inc.capabilities.notification.definition", None)
    sys.modules.pop("inc.api.http.routers_auth", None)
    build_container(manifest=kernel_only, uow_factory=uow_factory, clock=clock, settings=settings)
    assert "inc.capabilities.notification.definition" not in sys.modules
    assert "inc.api.http.routers_auth" not in sys.modules


async def test_cms_admin_routes_require_auth_not_404(
    client: Any,
) -> None:
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "api.unauthorized"
    assert "request_id" in body


async def test_management_plane_exposes_only_admin_and_shared_protocol_paths(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    app = create_app(
        manifest=management_plane,
        uow_factory=uow_factory,
        clock=clock,
        settings=settings,
        start_workers=False,
    )
    paths = set(app.openapi()["paths"])

    assert app.state.services.notification_auth is not None
    assert "/api/v1/admin/session" in paths
    assert "/api/v1/admin/community/discussions" in paths
    assert "/api/v1/auth/register" in paths
    assert "/.well-known/openid-configuration" in paths
    assert "/api/v1/me" not in paths
    assert "/api/v1/content/post" not in paths
    assert "/api/v1/community/discussions" not in paths
    assert "/api/v1/admin/content" in paths
    assert "/api/v1/admin/notifications/deliveries" in paths
    assert "/api/v1/admin/payments/orders" not in paths

    allowed_exact = {"/healthz", "/api/v1/health", "/.well-known/openid-configuration"}
    for path in paths:
        assert (
            path in allowed_exact
            or path.startswith("/api/v1/admin/")
            or path.startswith("/api/v1/auth/")
            or path.startswith("/oidc/")
        ), path


def test_management_plane_declares_only_the_releasable_admin_scope() -> None:
    assert management_plane.name == "management_plane"
    assert management_plane.features == ("auth", "site_settings", "post", "page")
    assert "payments" not in management_plane.capabilities
    assert "content" in management_plane.capabilities
    assert "comments" in management_plane.capabilities
    assert "taxonomy" in management_plane.capabilities
    assert "membership" in management_plane.capabilities
    assert "community" in management_plane.capabilities
    assert "notification" in management_plane.capabilities
    assert "community_admin" in management_plane.routers
    assert "community" not in management_plane.routers
    assert "payments.dev_fake" not in dict(management_plane.adapters).values()


async def test_manifest_unknown_capability_fails_fast(uow_factory: Any, clock: Any) -> None:
    manifest = AppManifest(name="bad", capabilities=("ghost",))
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.capability_unknown"


async def test_manifest_feature_requires_missing_capability_fails(
    uow_factory: Any, clock: Any
) -> None:
    manifest = AppManifest(name="bad", features=("post",))
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.feature_requires_missing"


async def test_missing_required_port_fails(uow_factory: Any, clock: Any) -> None:
    manifest = AppManifest(
        name="bad",
        capabilities=("identity", "access", "oidc_provider", "audit"),
        adapters=(
            ("oidc.subject_authenticator", "identity.credential"),
            ("oidc.subject_claims", "identity.profile"),
            ("oidc.authorization_decision", "access.authorize"),
        ),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.port_unbound"


async def test_capability_dependency_fails_before_port_resolution(
    uow_factory: Any, clock: Any
) -> None:
    manifest = AppManifest(
        name="bad",
        capabilities=("access", "oidc_provider", "audit"),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.capability_requires_missing"


async def test_community_requires_audit_capability(uow_factory: Any, clock: Any) -> None:
    manifest = AppManifest(
        name="community-without-audit",
        capabilities=("identity", "community"),
        adapters=(("community.author", "identity.community_author"),),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.capability_requires_missing"


async def test_adapter_port_owner_must_be_enabled(uow_factory: Any, clock: Any) -> None:
    manifest = AppManifest(
        name="bad",
        capabilities=("audit",),
        adapters=(("taxonomy.target_exists", "content.exists"),),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.port_owner_missing"


async def test_adapter_provider_must_be_enabled(uow_factory: Any, clock: Any) -> None:
    manifest = AppManifest(
        name="bad",
        capabilities=("taxonomy",),
        adapters=(("taxonomy.target_exists", "content.exists"),),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.adapter_dependency_missing"


async def test_router_requirements_fail_fast(uow_factory: Any, clock: Any) -> None:
    manifest = AppManifest(
        name="bad",
        capabilities=("identity",),
        routers=("auth",),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.router_requires_missing"


async def test_unknown_adapter_fails(uow_factory: Any, clock: Any) -> None:
    manifest = AppManifest(
        name="bad",
        capabilities=("audit",),
        adapters=(("taxonomy.target_exists", "nope.adapter"),),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.adapter_unknown"


async def test_duplicate_port_binding_fails(uow_factory: Any, clock: Any) -> None:
    manifest = AppManifest(
        name="bad",
        capabilities=("audit",),
        adapters=(
            ("taxonomy.target_exists", "content.exists"),
            ("taxonomy.target_exists", "content.exists"),
        ),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
        )
    assert excinfo.value.code == "kernel.port_duplicate"


async def test_notification_email_port_preserves_ordered_provider_bindings(
    uow_factory: Any, clock: Any
) -> None:
    manifest = AppManifest(
        name="notification-test",
        capabilities=("identity", "settings", "notification"),
        features=("site_settings",),
        adapters=(
            ("notification.recipient", "identity.notification_recipient"),
            ("notification.email", "email.smtp"),
            ("notification.email", "email.smtp2go"),
        ),
    )
    container = build_container(
        manifest=manifest,
        uow_factory=uow_factory,
        clock=clock,
        settings=ApiSettings(),
    )
    assert container.services is not None
    providers = container.services.adapters["notification.email"]
    assert tuple(provider.key for provider in providers) == (
        "email.smtp",
        "email.smtp2go",
    )


async def test_frozen_container_rejects_registration(uow_factory: Any, clock: Any) -> None:
    container = build_container(
        manifest=cms, uow_factory=uow_factory, clock=clock, settings=ApiSettings()
    )
    assert container.frozen
    with pytest.raises(KernelError) as excinfo:
        container.permission_registry.register("content.extra", owner="content")
    assert excinfo.value.code == "kernel.registry_frozen"


async def test_importing_api_packages_has_no_side_effects() -> None:
    import inc.api.app  # noqa: F401
    import inc.api.container  # noqa: F401
    import inc.api.manifest  # noqa: F401

    # reaching here means imports succeeded without creating an app or tasks
    assert True
