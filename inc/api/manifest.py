"""Application manifest fixtures.

Contract source: context/spec/composition.md §2.3.

Three manifests cover the product life: ``kernel_only`` activates no
business capability, ``identity_provider`` activates the OIDC ring, ``cms``
activates the full product.

The ``cms`` manifest is the **development profile**: it binds the dev-only
adapter ``payments.dev_fake`` and the S3-compatible assets adapter so the full
loop runs against the Compose RustFS service. The payment adapter is rejected
at container build when
``ApiSettings.environment == "production"`` (``kernel.adapter_production_denied``),
so production must either set ``AIYA_ENVIRONMENT=production`` (fail-closed) or
mount a manifest that binds only audited providers. Do not deploy ``cms`` with
any other/unset environment value — real traffic would silently run on the fake
provider, which also ships a hardcoded webhook secret.

notification (R6) is not part of the closed loop yet; the manifest reflects
only shipped capabilities.
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
        "points",
        "payments",
        "membership",
    ),
    features=(
        "post",
        "page",
        "site_settings",
        "site_cleanup",
        "check_in",
        "point_purchase",
        "membership_purchase",
    ),
    adapters=(
        ("oidc.subject_authenticator", "identity.credential"),
        ("oidc.subject_claims", "identity.profile"),
        ("oidc.authorization_decision", "access.authorize"),
        ("oidc.security_events", "oidc.session_revoker"),
        ("taxonomy.target_exists", "content.exists"),
        ("assets.object_storage", "assets.s3"),
        ("payments.provider", "payments.dev_fake"),
        ("membership.subject_exists", "membership.subject_exists"),
        ("membership.points_ledger", "membership.points_ledger"),
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
        "execution",
        "oidc",
        "check_in",
        "points",
        "points_admin",
        "point_purchase",
        "payments",
        "membership_purchase",
    ),
    workers=("outbox", "workflow", "task"),
    cron_enabled=True,
)
