"""Release composition guardrails."""

from __future__ import annotations

from inc.api.manifest import release
from inc.kernel.boot import AppManifest


def test_release_is_the_only_exported_application_manifest() -> None:
    assert isinstance(release, AppManifest)
    assert release.name == "release"
    assert "payments" in release.capabilities
    assert "content_bucket" in release.features


def test_release_registers_all_runtime_selectable_provider_families() -> None:
    adapters = dict(release.adapters)
    assert adapters["notification.email"] == "email.smtp"
    assert adapters["payments.provider"] == "payments.paypal"
    assert adapters["assets.object_storage"] == "assets.s3"
    assert adapters["oidc.signing_keys"] == "oidc.filesystem_keys"


def test_release_http_allowlist_uses_consolidated_user_and_business_routes() -> None:
    forbidden = {"me", "check_in", "point_purchase", "membership_purchase", "payments"}
    assert not forbidden & set(release.routers)
    assert {"auth", "user_center", "business_center", "archive_admin"} <= set(release.routers)
    assert {"content_public", "content_bucket", "oidc"} <= set(release.routers)
