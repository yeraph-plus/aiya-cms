"""Single-release manifest activation and route allowlist tests."""

from __future__ import annotations

import sys
from typing import Any

import httpx
import pytest

from inc.api.app import create_app
from inc.api.config import ApiSettings
from inc.api.container import build_container
from inc.api.manifest import release
from inc.kernel.boot import AppManifest
from inc.kernel.errors import KernelError


@pytest.fixture
def settings(tmp_path: Any) -> ApiSettings:
    return ApiSettings(issuer="http://testserver", oidc_signing_key_dir=str(tmp_path / "keys"))


async def test_release_has_public_content_auth_and_admin_routes(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    app = create_app(
        manifest=release,
        uow_factory=uow_factory,
        clock=clock,
        settings=settings,
        start_workers=False,
    )
    paths = set(app.openapi()["paths"])
    assert "/api/v1/admin/session" in paths
    assert "/api/v1/content/{type_name}" in paths
    assert "/oidc/login" in paths
    assert "/oidc/token" in paths
    assert "/api/v1/admin/content-bucket/upload-intents" in paths
    assert "/api/v1/me" not in paths
    assert not any("/api/v1/auth/" in path for path in paths)
    assert not any("purchase" in path or "/payments" in path for path in paths)


async def test_release_admin_route_requires_auth(client: Any) -> None:
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 401
    assert response.json()["code"] == "api.unauthorized"


async def test_release_public_content_route_is_mounted(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    app = create_app(
        manifest=release,
        uow_factory=uow_factory,
        clock=clock,
        settings=settings,
        start_workers=False,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/content/post")
    assert response.status_code != 404


async def test_unknown_manifest_capability_fails_fast(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    with pytest.raises(KernelError) as exc_info:
        build_container(
            manifest=AppManifest(name="bad", capabilities=("ghost",)),
            uow_factory=uow_factory,
            clock=clock,
            settings=settings,
        )
    assert exc_info.value.code == "kernel.capability_unknown"


async def test_importing_composition_modules_has_no_side_effects() -> None:
    sys.modules.pop("inc.api.manifest", None)
    import inc.api.app  # noqa: F401
    import inc.api.container  # noqa: F401
    import inc.api.manifest  # noqa: F401
