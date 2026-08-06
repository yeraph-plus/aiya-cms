"""Application manifest fixtures.

Contract source: context/spec/composition.md §2.3.

Three manifests cover the product life: ``kernel_only`` activates no
business capability, ``identity_provider`` activates the OIDC ring, ``cms``
activates the full product. The production entry point is the ``cms``
manifest; nothing starts unless its scope says so.

R6/R7 (notification, points, payments) are not part of the first closed
loop; the manifest reflects only shipped capabilities.
"""

from __future__ import annotations

from inc.kernel.boot import AppManifest

kernel_only = AppManifest(name="kernel_only")

identity_provider = AppManifest(
    name="identity_provider",
    capabilities=("identity", "access", "oidc_provider", "audit"),
    adapters=(
        ("oidc.subject_authenticator", "identity.credential"),
        ("oidc.subject_claims", "identity.profile"),
        ("oidc.authorization_decision", "access.authorize"),
        ("oidc.security_events", "oidc.session_revoker"),
    ),
)

cms = AppManifest(
    name="cms",
    capabilities=(
        "identity",
        "access",
        "oidc_provider",
        "audit",
        "settings",
        "content",
        "taxonomy",
        "assets",
    ),
    features=("post", "page"),
    adapters=(
        ("oidc.subject_authenticator", "identity.credential"),
        ("oidc.subject_claims", "identity.profile"),
        ("oidc.authorization_decision", "access.authorize"),
        ("oidc.security_events", "oidc.session_revoker"),
        ("taxonomy.target_exists", "content.exists"),
        ("assets.object_storage", "assets.dev_memory"),
    ),
    routers=(
        "health",
        "auth",
        "identity",
        "access",
        "content",
        "taxonomy",
        "settings",
        "assets",
        "audit",
        "oidc",
    ),
    workers=("outbox", "workflow"),
    cron_enabled=True,
)
