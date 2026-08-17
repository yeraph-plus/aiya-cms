"""Guards: the three manifest fixtures activate exactly the declared scope.

Contract source: context/spec/composition.md §2.3, context/spec/quality-release.md §8.

``kernel_only`` activates no business capability, ``identity_provider``
activates the OIDC ring only, ``cms`` activates the full product. Anything
that starts at runtime must be traceable to one of these manifests (or a
production manifest with the same shape).
"""

from __future__ import annotations

from inc.api.manifest import cms, cms_dev, identity_provider, kernel_only, management_plane
from inc.kernel.boot import AppManifest

ALL_CAPABILITIES = (
    "identity",
    "access",
    "oidc_provider",
    "audit",
    "settings",
    "content",
    "comments",
    "community",
    "notification",
    "taxonomy",
    "assets",
    "points",
    "payments",
    "membership",
    "engagement",
)

ALL_FEATURES = (
    "auth",
    "post",
    "page",
    "site_settings",
    "check_in",
    "point_purchase",
    "membership_purchase",
    "site_cleanup",
    "content_engagement",
)


def test_manifest_fixtures_are_immutable_and_named() -> None:
    for manifest, expected in (
        (kernel_only, "kernel_only"),
        (identity_provider, "identity_provider"),
        (management_plane, "management_plane"),
        (cms, "cms"),
    ):
        assert isinstance(manifest, AppManifest)
        assert manifest.name == expected


def test_kernel_only_manifest_activates_no_business_scope() -> None:
    assert kernel_only.capabilities == ()
    assert kernel_only.features == ()
    assert kernel_only.routers == ()
    assert kernel_only.workers == ()
    assert not kernel_only.cron_enabled


def test_identity_provider_manifest_activates_oidc_ring_only() -> None:
    assert set(identity_provider.capabilities) == {"identity", "access", "oidc_provider", "audit"}
    assert identity_provider.features == ()
    assert identity_provider.routers == ()


def test_cms_manifest_activates_full_product() -> None:
    assert set(cms.capabilities) == set(ALL_CAPABILITIES)
    assert set(cms.features) == set(ALL_FEATURES)


def test_cms_production_manifest_does_not_bind_test_adapters() -> None:
    adapters = dict(cms.adapters)
    assert adapters["oidc.signing_keys"] == "oidc.filesystem_keys"
    assert adapters["payments.provider"] == "payments.paypal"
    dev_adapters = dict(cms_dev.adapters)
    assert dev_adapters["oidc.signing_keys"] == "oidc.in_memory_keys"
    assert dev_adapters["payments.provider"] == "payments.dev_fake"


def test_management_plane_is_the_only_deployable_profile() -> None:
    assert "notifications_admin" in management_plane.routers
    assert "payments" not in management_plane.capabilities
    assert "oidc.in_memory_keys" not in dict(management_plane.adapters).values()
    assert "payments.dev_fake" not in dict(management_plane.adapters).values()
