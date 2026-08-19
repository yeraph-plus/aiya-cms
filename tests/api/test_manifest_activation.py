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
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/verify-email" in paths
    assert "/api/v1/auth/password-reset/request" in paths
    assert "/api/v1/auth/password-reset/confirm" in paths
    assert "/api/v1/me" in paths
    assert "/api/v1/me/purchases" in paths
    assert "/api/v1/business/quotes" in paths
    assert "/api/v1/admin/archive/items" in paths


def test_release_uses_consolidated_features_and_routers() -> None:
    assert "user_center" in release.features
    assert "business_center" in release.features
    assert "check_in" not in release.features
    assert "membership_grants" not in release.features
    assert {"user_center", "business_center", "archive_admin"} <= set(release.routers)
    assert "check_in" not in release.routers


def test_release_builds_frozen_catalogs_and_workflow_handlers(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    container = build_container(
        manifest=release,
        uow_factory=uow_factory,
        clock=clock,
        settings=settings,
    )
    services = container.services
    assert services is not None
    assert services.point_bundles is not None and services.point_bundles.frozen
    assert services.membership_offers is not None and services.membership_offers.frozen
    assert services.gift_card_fulfillments is not None
    assert services.gift_card_fulfillments.frozen
    assert services.business_products is not None and services.business_products.frozen
    assert services.point_bundles.require("points.basic").points_amount == 1000
    assert services.business_products.require("archive.download.manifest").client_ids == frozenset(
        {"aiya-site"}
    )
    assert services.archive_queries is not None
    assert services.archive_admin is not None
    assert services.archive_link_resolver is not None
    assert set(services.provider_catalogs["archive.delivery"].keys()) == {
        "archive.gofile",
        "archive.openlist",
    }
    assert set(container.workflow_registry.keys()) >= {
        "user_center.check_in.v1",
        "user_center.point_purchase.fulfill.v1",
        "user_center.membership_purchase.fulfill.v1",
        "user_center.gift_card.points.v1",
        "user_center.gift_card.membership.v1",
        "user_center.refund.compensate.v1",
        "business_center.consume.v1",
    }
    assert {
        handler.key for handler in container.handler_registry.handlers_for("payment.captured.v1")
    } == {"user_center.payment_captured.v1"}
    assert {
        handler.key
        for handler in container.handler_registry.handlers_for("payment.refund_completed.v1")
    } == {"user_center.payment_refund_completed.v1"}


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
