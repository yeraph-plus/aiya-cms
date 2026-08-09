"""Site settings feature: declarative settings groups in one place.

Contract source: context/spec/features.md §4.5, context/spec/capabilities/settings.md §2/§5.

The site_settings feature owns the site-level settings group
declarations (general, seo, notification). settings itself stays a
passive host: it persists, validates, gates by permission and serves
groups that downstream code declares. SMTP connection credentials
(host/port/username/password/from_address, use_tls/starttls) are filled
through the ``notification`` group; the password is registered as a
sensitive field and never leaves the admin/private surface.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from inc.capabilities.settings import SettingGroupSpec
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="site_settings", version="1", requires=("settings",))

GENERAL_GROUP_KEY = "general"
SEO_GROUP_KEY = "seo"
NOTIFICATION_GROUP_KEY = "notification"
ENTITLEMENTS_GROUP_KEY = "entitlements"


class GeneralValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_tagline: str = Field(default="", max_length=200)
    default_locale: str = Field(default="zh-CN", max_length=20)
    default_timezone: str = Field(default="Asia/Shanghai", max_length=50)
    maintenance_mode: bool = False


GENERAL_PUBLIC_FIELDS = (
    "site_tagline",
    "default_locale",
    "default_timezone",
    "maintenance_mode",
)


class SeoValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_name: str = Field(default="aiya", max_length=100)
    default_title_template: str = Field(default="{title} - aiya", max_length=200)
    default_description: str = Field(default="", max_length=300)
    default_share_image_asset_id: uuid.UUID | None = None
    robots_policy: str = Field(default="index,follow", max_length=50)
    canonical_host: str | None = Field(default=None, max_length=200)


SEO_PUBLIC_FIELDS = (
    "site_name",
    "default_title_template",
    "default_description",
    "default_share_image_asset_id",
    "robots_policy",
    "canonical_host",
)


class NotificationValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_from_name: str = Field(default="aiya", max_length=100)
    email_enabled: bool = True
    default_channel: str = Field(default="email", max_length=20)
    smtp_host: str = Field(default="", max_length=200)
    smtp_port: int = Field(default=25, ge=1, le=65535)
    smtp_username: str = Field(default="", max_length=200)
    smtp_password: SecretStr | None = Field(default=None, max_length=200)
    smtp_from_address: str = Field(default="no-reply@aiya.local", max_length=200)
    smtp_use_tls: bool = False
    smtp_starttls: bool = False


NOTIFICATION_PUBLIC_FIELDS = ("default_from_name", "email_enabled", "default_channel")

NOTIFICATION_SENSITIVE_FIELDS = ("smtp_password",)


class EntitlementsValueSchema(BaseModel):
    """Configurable entitlement amounts awarded by business flows.

    Points grants are never computed here; these values are read by
    features (registration reward, invite reward, gift quota) and passed
    as fixed amounts to points behaviors. All values are whole points.
    """

    model_config = ConfigDict(extra="forbid")

    registration_reward: int = Field(default=0, ge=0, le=1_000_000)
    invite_reward: int = Field(default=0, ge=0, le=1_000_000)
    gift_quota: int = Field(default=0, ge=0, le=1_000_000)


ENTITLEMENTS_PUBLIC_FIELDS = ("registration_reward", "invite_reward", "gift_quota")


def build_site_setting_group_specs() -> tuple[SettingGroupSpec, ...]:
    return (
        SettingGroupSpec(
            group_key=GENERAL_GROUP_KEY,
            version="1",
            value_schema=GeneralValueSchema,
            public_fields=GENERAL_PUBLIC_FIELDS,
            update_permission="settings.general.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=SEO_GROUP_KEY,
            version="1",
            value_schema=SeoValueSchema,
            public_fields=SEO_PUBLIC_FIELDS,
            update_permission="settings.seo.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=NOTIFICATION_GROUP_KEY,
            version="1",
            value_schema=NotificationValueSchema,
            public_fields=NOTIFICATION_PUBLIC_FIELDS,
            sensitive_fields=NOTIFICATION_SENSITIVE_FIELDS,
            update_permission="settings.notification.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=ENTITLEMENTS_GROUP_KEY,
            version="1",
            value_schema=EntitlementsValueSchema,
            public_fields=ENTITLEMENTS_PUBLIC_FIELDS,
            update_permission="settings.entitlements.update",
            cache_policy="event",
        ),
    )
