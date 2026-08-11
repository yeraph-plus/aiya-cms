"""Site settings feature: declarative settings groups in one place.

Contract source: context/spec/features.md §4.5, context/spec/capabilities/settings.md §2/§5.

The site_settings feature owns the site-level settings group
declarations (general, seo, notification, object_storage, entitlements and
operations). settings itself stays a
passive host: it persists, validates, gates by permission and serves
groups that downstream code declares. SMTP connection credentials
(host/port/username/password/from_address, use_tls/starttls) are filled
through the ``notification`` group; the password is registered as a
sensitive field and never leaves the admin/private surface.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from inc.capabilities.settings import (
    SettingFieldMetadata,
    SettingFieldSpec,
    SettingGroupSpec,
    SettingOption,
)
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="site_settings", version="1", requires=("settings",))

GENERAL_GROUP_KEY = "general"
SEO_GROUP_KEY = "seo"
NOTIFICATION_GROUP_KEY = "notification"
ENTITLEMENTS_GROUP_KEY = "entitlements"
OBJECT_STORAGE_GROUP_KEY = "object_storage"
OPERATIONS_GROUP_KEY = "operations"


class GeneralValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_tagline: str = Field(default="", max_length=200)
    site_logo_asset_id: uuid.UUID | None = None
    default_locale: str = Field(default="zh-CN", max_length=20)
    default_timezone: str = Field(default="Asia/Shanghai", max_length=50)
    maintenance_mode: bool = False


class SeoValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_name: str = Field(default="aiya", max_length=100)
    default_title_template: str = Field(default="{title} - aiya", max_length=200)
    default_description: str = Field(default="", max_length=300)
    default_share_image_asset_id: uuid.UUID | None = None
    robots_policy: str = Field(default="index,follow", max_length=50)
    canonical_host: str | None = Field(default=None, max_length=200)


class NotificationValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_from_name: str = Field(default="aiya", max_length=100)
    email_enabled: bool = False
    default_channel: str = Field(default="email", max_length=20)
    smtp_enabled: bool = False
    smtp_host: str = Field(default="", max_length=200)
    smtp_port: int = Field(default=25, ge=1, le=65535)
    smtp_username: str = Field(default="", max_length=200)
    smtp_password: SecretStr | None = Field(default=None, max_length=200)
    smtp_from_address: str = Field(default="no-reply@aiya.local", max_length=200)
    smtp_use_tls: bool = False
    smtp_starttls: bool = False
    smtp2go_enabled: bool = False
    smtp2go_api_key: SecretStr | None = Field(default=None, max_length=200)
    smtp2go_region: Literal["global", "us", "eu"] = "global"

    @model_validator(mode="after")
    def _validate_tls_modes(self) -> NotificationValueSchema:
        if self.smtp_use_tls and self.smtp_starttls:
            raise ValueError("smtp_use_tls and smtp_starttls are mutually exclusive")
        return self


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


class ObjectStorageValueSchema(BaseModel):
    """S3-compatible endpoint and credentials for the assets adapter."""

    model_config = ConfigDict(extra="forbid")

    s3_endpoint_url: str = Field(default="", max_length=500)
    s3_virtual_host_url: str = Field(default="", max_length=500)
    s3_bucket: str = Field(default="aiya-assets", max_length=200)
    s3_avatar_bucket: str = Field(default="aiya-avatars", max_length=200)
    s3_region: str = Field(default="us-east-1", max_length=100)
    s3_addressing_style: Literal["path", "virtual"] = "path"
    s3_access_key_id: SecretStr | None = Field(default=None, max_length=200)
    s3_secret_access_key: SecretStr | None = Field(default=None, max_length=200)


class OperationsValueSchema(BaseModel):
    """Operational retention policy consumed by explicit maintenance tasks."""

    model_config = ConfigDict(extra="forbid")

    audit_retention_days: int = Field(default=30, ge=1, le=3650)


def _option(label: str, value: str | int | float | bool | None) -> SettingOption:
    return SettingOption(label=label, value=value)


GENERAL_FIELDS = (
    SettingFieldSpec(
        slug="site_tagline",
        title="Site tagline",
        desc="Short tagline shown with the site identity.",
        type="text",
        default="",
        metadata=SettingFieldMetadata(max_length=200),
        public=True,
    ),
    SettingFieldSpec(
        slug="site_logo_asset_id",
        title="Site logo",
        desc="Image asset used as the site logo.",
        type="upload",
        type_sub="single",
        default=None,
        metadata=SettingFieldMetadata(accept=("image/*",)),
        public=True,
    ),
    SettingFieldSpec(
        slug="default_locale",
        title="Default locale",
        desc="Locale used when a request does not specify one.",
        type="select",
        type_sub="string",
        default="zh-CN",
        metadata=SettingFieldMetadata(
            options=(_option("简体中文", "zh-CN"), _option("English", "en-US")),
        ),
        public=True,
    ),
    SettingFieldSpec(
        slug="default_timezone",
        title="Default timezone",
        desc="Timezone used for site-level date and time display.",
        type="text",
        type_sub="timezone",
        default="Asia/Shanghai",
        metadata=SettingFieldMetadata(max_length=50),
        public=True,
    ),
    SettingFieldSpec(
        slug="maintenance_mode",
        title="Maintenance mode",
        desc="Whether the site is in maintenance mode.",
        type="bool",
        default=False,
        public=True,
    ),
)

SEO_FIELDS = (
    SettingFieldSpec(
        slug="site_name",
        title="Site name",
        desc="Canonical site name used by the frontend.",
        type="text",
        default="aiya",
        metadata=SettingFieldMetadata(max_length=100),
        public=True,
    ),
    SettingFieldSpec(
        slug="default_title_template",
        title="Default title template",
        desc="Template for pages that do not provide their own title.",
        type="text",
        default="{title} - aiya",
        metadata=SettingFieldMetadata(max_length=200),
        public=True,
    ),
    SettingFieldSpec(
        slug="default_description",
        title="Default description",
        desc="Default description for pages without a custom description.",
        type="textarea",
        default="",
        metadata=SettingFieldMetadata(rows=4, max_length=300),
        public=True,
    ),
    SettingFieldSpec(
        slug="default_share_image_asset_id",
        title="Default share image",
        desc="Asset used when a page does not provide a share image.",
        type="upload",
        type_sub="single",
        default=None,
        metadata=SettingFieldMetadata(accept=("image/*",)),
        public=True,
    ),
    SettingFieldSpec(
        slug="robots_policy",
        title="Robots policy",
        desc="Default robots policy exposed to the frontend.",
        type="select",
        type_sub="string",
        default="index,follow",
        metadata=SettingFieldMetadata(
            options=(
                _option("Index and follow", "index,follow"),
                _option("No index and no follow", "noindex,nofollow"),
                _option("Index and no follow", "index,nofollow"),
                _option("No index and follow", "noindex,follow"),
            )
        ),
        public=True,
    ),
    SettingFieldSpec(
        slug="canonical_host",
        title="Canonical host",
        desc="Optional canonical host used by the frontend.",
        type="text",
        type_sub="url",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        public=True,
    ),
)

NOTIFICATION_FIELDS = (
    SettingFieldSpec(
        slug="default_from_name",
        title="Default sender name",
        desc="Display name used for notification messages.",
        type="text",
        default="aiya",
        metadata=SettingFieldMetadata(max_length=100),
        public=True,
    ),
    SettingFieldSpec(
        slug="email_enabled",
        title="Email enabled",
        desc="Whether email delivery is enabled.",
        type="bool",
        default=False,
        public=True,
    ),
    SettingFieldSpec(
        slug="default_channel",
        title="Default channel",
        desc="Channel selected when a notification does not specify one.",
        type="select",
        type_sub="string",
        default="email",
        metadata=SettingFieldMetadata(options=(_option("Email", "email"),)),
        public=True,
    ),
    SettingFieldSpec(
        slug="smtp_enabled",
        title="SMTP enabled",
        desc="Use the aiosmtplib SMTP provider when email delivery is enabled.",
        type="bool",
        default=False,
    ),
    SettingFieldSpec(
        slug="smtp_host",
        title="SMTP host",
        desc="SMTP server hostname.",
        type="text",
        default="",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="smtp_port",
        title="SMTP port",
        desc="SMTP server port.",
        type="text",
        type_sub="integer",
        default=25,
        metadata=SettingFieldMetadata(max_length=5),
    ),
    SettingFieldSpec(
        slug="smtp_username",
        title="SMTP username",
        desc="Optional SMTP authentication username.",
        type="text",
        default="",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="smtp_password",
        title="SMTP password",
        desc="Optional SMTP authentication password.",
        type="text",
        type_sub="password",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        sensitive=True,
    ),
    SettingFieldSpec(
        slug="smtp_from_address",
        title="SMTP from address",
        desc="Address used in the From header.",
        type="text",
        type_sub="email",
        default="no-reply@aiya.local",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="smtp_use_tls",
        title="SMTP implicit TLS",
        desc="Use TLS immediately when connecting to SMTP.",
        type="bool",
        default=False,
    ),
    SettingFieldSpec(
        slug="smtp_starttls",
        title="SMTP STARTTLS",
        desc="Upgrade a plain SMTP connection with STARTTLS.",
        type="bool",
        default=False,
    ),
    SettingFieldSpec(
        slug="smtp2go_enabled",
        title="SMTP2GO enabled",
        desc="Use the SMTP2GO REST provider when email delivery is enabled.",
        type="bool",
        default=False,
    ),
    SettingFieldSpec(
        slug="smtp2go_api_key",
        title="SMTP2GO API key",
        desc="Write-only API key used for SMTP2GO REST requests.",
        type="text",
        type_sub="password",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        sensitive=True,
    ),
    SettingFieldSpec(
        slug="smtp2go_region",
        title="SMTP2GO region",
        desc="Fixed SMTP2GO API region endpoint.",
        type="select",
        type_sub="string",
        default="global",
        metadata=SettingFieldMetadata(
            options=(
                _option("Global", "global"),
                _option("United States", "us"),
                _option("European Union", "eu"),
            )
        ),
    ),
)

ENTITLEMENTS_FIELDS = (
    SettingFieldSpec(
        slug="registration_reward",
        title="Registration reward",
        desc="Points granted by the registration feature.",
        type="text",
        type_sub="integer",
        default=0,
        metadata=SettingFieldMetadata(max_length=7),
        public=True,
    ),
    SettingFieldSpec(
        slug="invite_reward",
        title="Invite reward",
        desc="Points granted by the invitation feature.",
        type="text",
        type_sub="integer",
        default=0,
        metadata=SettingFieldMetadata(max_length=7),
        public=True,
    ),
    SettingFieldSpec(
        slug="gift_quota",
        title="Gift quota",
        desc="Points available to the gift flow.",
        type="text",
        type_sub="integer",
        default=0,
        metadata=SettingFieldMetadata(max_length=7),
        public=True,
    ),
)

OBJECT_STORAGE_FIELDS = (
    SettingFieldSpec(
        slug="s3_endpoint_url",
        title="S3 endpoint URL",
        desc="S3-compatible API endpoint.",
        type="text",
        type_sub="url",
        default="",
        metadata=SettingFieldMetadata(max_length=500),
    ),
    SettingFieldSpec(
        slug="s3_virtual_host_url",
        title="S3 virtual host URL",
        desc="Optional virtual-host endpoint template.",
        type="text",
        type_sub="url",
        default="",
        metadata=SettingFieldMetadata(max_length=500),
    ),
    SettingFieldSpec(
        slug="s3_bucket",
        title="S3 bucket",
        desc="System bucket used for site resources.",
        type="text",
        default="aiya-assets",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="s3_avatar_bucket",
        title="S3 avatar bucket",
        desc="Dedicated bucket used for user avatars.",
        type="text",
        default="aiya-avatars",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="s3_region",
        title="S3 region",
        desc="S3 signing region.",
        type="text",
        default="us-east-1",
        metadata=SettingFieldMetadata(max_length=100),
    ),
    SettingFieldSpec(
        slug="s3_addressing_style",
        title="S3 addressing style",
        desc="Addressing mode used by the S3 client.",
        type="select",
        type_sub="string",
        default="path",
        metadata=SettingFieldMetadata(
            options=(_option("Path", "path"), _option("Virtual host", "virtual")),
        ),
    ),
    SettingFieldSpec(
        slug="s3_access_key_id",
        title="S3 access key ID",
        desc="S3-compatible provider access key.",
        type="text",
        type_sub="password",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        sensitive=True,
    ),
    SettingFieldSpec(
        slug="s3_secret_access_key",
        title="S3 secret access key",
        desc="S3-compatible provider secret key.",
        type="text",
        type_sub="password",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        sensitive=True,
    ),
)

OPERATIONS_FIELDS = (
    SettingFieldSpec(
        slug="audit_retention_days",
        title="Audit and execution log retention (days)",
        desc="How many days audit and terminal automatic execution records are retained.",
        type="text",
        type_sub="integer",
        default=30,
        metadata=SettingFieldMetadata(max_length=4),
    ),
)


def build_site_setting_group_specs() -> tuple[SettingGroupSpec, ...]:
    return (
        SettingGroupSpec(
            group_key=GENERAL_GROUP_KEY,
            version="1",
            value_schema=GeneralValueSchema,
            fields=GENERAL_FIELDS,
            update_permission="settings.general.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=SEO_GROUP_KEY,
            version="1",
            value_schema=SeoValueSchema,
            fields=SEO_FIELDS,
            update_permission="settings.seo.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=NOTIFICATION_GROUP_KEY,
            version="1",
            value_schema=NotificationValueSchema,
            fields=NOTIFICATION_FIELDS,
            update_permission="settings.notification.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=ENTITLEMENTS_GROUP_KEY,
            version="1",
            value_schema=EntitlementsValueSchema,
            fields=ENTITLEMENTS_FIELDS,
            update_permission="settings.entitlements.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=OBJECT_STORAGE_GROUP_KEY,
            version="1",
            value_schema=ObjectStorageValueSchema,
            fields=OBJECT_STORAGE_FIELDS,
            update_permission="settings.object_storage.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=OPERATIONS_GROUP_KEY,
            version="1",
            value_schema=OperationsValueSchema,
            fields=OPERATIONS_FIELDS,
            update_permission="settings.operations.update",
            cache_policy="event",
        ),
    )
