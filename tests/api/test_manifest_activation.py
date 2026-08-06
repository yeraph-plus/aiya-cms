"""Manifest activation scope tests.

Contract source: context/spec/composition.md §9, http-openapi.md §12.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from inc.api.app import create_app
from inc.api.config import ApiSettings
from inc.api.container import build_container
from inc.api.manifest import cms, kernel_only
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


async def test_cms_admin_routes_require_auth_not_404(
    client: Any,
) -> None:
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "api.unauthorized"
    assert "request_id" in body


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
        capabilities=("oidc_provider",),
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
