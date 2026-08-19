"""The single deployable application composition.

Contract source: context/spec/composition.md §2.3.

``release`` serves the administration plane together with the public content
and OIDC surfaces used by the Astro client. Test transports and temporary
filesystem key directories use the same release contracts; no alternate
runtime composition or fake payment provider exists.
"""

from __future__ import annotations

from inc.kernel.boot import AppManifest

release = AppManifest(
    name="release",
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
        "payments",
        "engagement",
        "gift_cards",
        "archive",
    ),
    features=(
        "auth",
        "site_settings",
        "site_cleanup",
        "post",
        "page",
        "content_engagement",
        "content_bucket",
        "work",
        "user_center",
        "business_center",
    ),
    adapters=(
        ("oidc.subject_authenticator", "identity.credential"),
        ("oidc.subject_claims", "identity.profile"),
        ("oidc.authorization_decision", "access.authorize"),
        ("oidc.security_events", "oidc.session_revoker"),
        ("oidc.signing_keys", "oidc.filesystem_keys"),
        ("assets.object_storage", "assets.s3"),
        ("payments.provider", "payments.paypal"),
        ("community.author", "identity.community_author"),
        ("taxonomy.target_exists", "content.exists"),
        ("comments.target_exists", "content.exists"),
        ("membership.subject_exists", "membership.subject_exists"),
        ("archive.delivery", "archive.openlist"),
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
        "community",
        "content",
        "content_public",
        "comments",
        "taxonomy",
        "settings",
        "assets",
        "content_bucket",
        "audit",
        "execution",
        "notifications_admin",
        "oidc",
        "points_admin",
        "membership_admin",
        "gift_cards_admin",
        "archive_admin",
        "user_center",
        "business_center",
        "oidc_admin",
    ),
    workers=("outbox", "workflow", "task"),
    cron_enabled=True,
)
