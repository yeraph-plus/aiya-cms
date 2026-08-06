"""Application manifest fixtures.

Contract source: context/spec/composition.md §2.3.

Three manifests cover the product life: ``kernel_only`` activates no
business capability, ``identity_provider`` activates the OIDC ring, ``cms``
activates the full product. The production entry point is the ``cms``
manifest; nothing starts unless its scope says so.
"""

from __future__ import annotations

from inc.kernel.boot import AppManifest

kernel_only = AppManifest(name="kernel_only")

identity_provider = AppManifest(
    name="identity_provider",
    capabilities=("identity", "access", "oidc_provider", "audit"),
)

cms = AppManifest(
    name="cms",
    capabilities=(
        "identity",
        "access",
        "oidc_provider",
        "audit",
        "settings",
        "notification",
        "content",
        "taxonomy",
        "assets",
        "points",
        "payments",
    ),
    features=("post", "page", "check_in", "point_purchase"),
)
