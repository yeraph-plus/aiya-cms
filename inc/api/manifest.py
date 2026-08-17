"""Application manifest fixtures.

Contract source: context/spec/composition.md §2.3.

Four manifests cover the current release boundary: ``kernel_only`` activates
no business capability, ``identity_provider`` activates the development OIDC
ring, ``management_plane`` is the deployable administrator control plane, and
``cms`` activates the full product with production adapters. ``cms_dev`` is the
explicit local/test profile; it is the only profile that binds in-memory OIDC
keys or the deterministic fake payment provider.

The production ``cms`` manifest binds filesystem-backed OIDC signing keys and
the PayPal adapter. PayPal credentials and webhook id are validated when the
adapter is constructed for a production environment. The S3-compatible assets
adapter remains settings-backed so the same manifest can target RustFS or an
external S3 service.

notification is enabled with the settings-backed SMTP adapter. Constructing
the adapter opens no connection; provider I/O occurs only inside an explicitly
started delivery workflow.
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
        ("oidc.signing_keys", "oidc.in_memory_keys"),
    ),
)

management_plane = AppManifest(
    name="management_plane",
    capabilities=(
        "identity",
        "access",
        "oidc_provider",
        "audit",
        "settings",
        "assets",
        "points",
        "community",
        "content",
        "comments",
        "taxonomy",
        "membership",
        "notification",
    ),
    features=("auth", "site_settings", "post", "page"),
    adapters=(
        ("oidc.subject_authenticator", "identity.credential"),
        ("oidc.subject_claims", "identity.profile"),
        ("oidc.authorization_decision", "access.authorize"),
        ("oidc.security_events", "oidc.session_revoker"),
        ("oidc.signing_keys", "oidc.filesystem_keys"),
        ("assets.object_storage", "assets.s3"),
        ("community.author", "identity.community_author"),
        ("taxonomy.target_exists", "content.exists"),
        ("comments.target_exists", "content.exists"),
        ("membership.subject_exists", "membership.subject_exists"),
        ("membership.points_ledger", "membership.points_ledger"),
        ("notification.recipient", "identity.notification_recipient"),
        ("notification.email", "email.smtp"),
    ),
    routers=(
        "health",
        "auth",
        "admin_session",
        "dashboard",
        "identity",
        "access",
        "community_admin",
        "content",
        "comments_admin",
        "taxonomy",
        "settings",
        "assets",
        "audit",
        "execution",
        "notifications_admin",
        "oidc",
        "points_admin",
        "membership_admin",
        "oidc_admin",
    ),
    workers=("outbox", "workflow", "task"),
    cron_enabled=True,
)

_CMS_CAPABILITIES = (
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

_CMS_FEATURES = (
    "auth",
    "post",
    "page",
    "site_settings",
    "site_cleanup",
    "check_in",
    "point_purchase",
    "membership_purchase",
    "content_engagement",
)

_CMS_ROUTERS = (
    "health",
    "dashboard",
    "auth",
    "me",
    "admin_session",
    "identity",
    "access",
    "content",
    "content_public",
    "comments",
    "community",
    "notifications_admin",
    "engagement",
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
    "membership_admin",
    "oidc_admin",
)

_CMS_WORKERS = ("outbox", "workflow", "task")

_CMS_COMMON_ADAPTERS = (
    ("oidc.subject_authenticator", "identity.credential"),
    ("oidc.subject_claims", "identity.profile"),
    ("oidc.authorization_decision", "access.authorize"),
    ("oidc.security_events", "oidc.session_revoker"),
    ("taxonomy.target_exists", "content.exists"),
    ("comments.target_exists", "content.exists"),
    ("community.author", "identity.community_author"),
    ("notification.recipient", "identity.notification_recipient"),
    ("notification.email", "email.smtp"),
    ("assets.object_storage", "assets.s3"),
    ("membership.subject_exists", "membership.subject_exists"),
    ("membership.points_ledger", "membership.points_ledger"),
)

cms = AppManifest(
    name="cms",
    capabilities=_CMS_CAPABILITIES,
    features=_CMS_FEATURES,
    adapters=(
        ("oidc.signing_keys", "oidc.filesystem_keys"),
        *_CMS_COMMON_ADAPTERS,
        ("payments.provider", "payments.paypal"),
    ),
    routers=_CMS_ROUTERS,
    workers=_CMS_WORKERS,
    cron_enabled=True,
)

cms_dev = AppManifest(
    name="cms_dev",
    capabilities=_CMS_CAPABILITIES,
    features=_CMS_FEATURES,
    adapters=(
        ("oidc.signing_keys", "oidc.in_memory_keys"),
        *_CMS_COMMON_ADAPTERS,
        ("payments.provider", "payments.dev_fake"),
    ),
    routers=_CMS_ROUTERS,
    workers=_CMS_WORKERS,
    cron_enabled=True,
)
