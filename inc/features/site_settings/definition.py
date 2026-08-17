"""Code-owned site settings declarations.

The backend exports only stable field identities, value types and structural
constraints.  Labels, help text, placeholders and option captions are owned
by the localized administration client.
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

spec = FeatureSpec(name="site_settings", version="2", requires=("settings",))

GENERAL_GROUP_KEY = "general"
SEO_GROUP_KEY = "seo"
NOTIFICATION_GROUP_KEY = "notification"
ENTITLEMENTS_GROUP_KEY = "entitlements"
OBJECT_STORAGE_GROUP_KEY = "object_storage"
OPERATIONS_GROUP_KEY = "operations"
PAYMENTS_GROUP_KEY = "payments"


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
    default_channel: Literal["email"] = "email"
    email_provider: Literal["email.smtp", "email.smtp2go"] = "email.smtp"
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
    model_config = ConfigDict(extra="forbid")

    registration_reward: int = Field(default=0, ge=0, le=1_000_000)
    invite_reward: int = Field(default=0, ge=0, le=1_000_000)
    gift_quota: int = Field(default=0, ge=0, le=1_000_000)


class ObjectStorageValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_provider: Literal["s3"] = "s3"
    s3_endpoint_url: str = Field(default="", max_length=500)
    s3_virtual_host_url: str = Field(default="", max_length=500)
    s3_public_base_url: str = Field(default="", max_length=500)
    s3_bucket: str = Field(default="aiya-assets", max_length=200)
    s3_avatar_bucket: str = Field(default="aiya-avatars", max_length=200)
    s3_content_bucket: str = Field(default="aiya-content", max_length=200)
    s3_region: str = Field(default="us-east-1", max_length=100)
    s3_addressing_style: Literal["path", "virtual"] = "path"
    s3_access_key_id: SecretStr | None = Field(default=None, max_length=200)
    s3_secret_access_key: SecretStr | None = Field(default=None, max_length=200)
    content_image_max_edge: int = Field(default=2560, ge=1, le=8192)
    content_image_webp_quality: int = Field(default=85, ge=40, le=100)


class OperationsValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_retention_days: int = Field(default=30, ge=1, le=3650)


class PaymentsValueSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["paypal", "epay"] = "paypal"
    paypal_environment: Literal["sandbox", "production"] = "sandbox"
    paypal_client_id: str = Field(default="", max_length=200)
    paypal_client_secret: SecretStr | None = Field(default=None, max_length=200)
    paypal_webhook_id: str = Field(default="", max_length=200)
    epay_gateway_url: str = Field(default="", max_length=500)
    epay_merchant_id: str = Field(default="", max_length=200)
    epay_merchant_key: SecretStr | None = Field(default=None, max_length=200)
    epay_payment_type: str = Field(default="alipay", max_length=50)


def _option(value: str | int | float | bool | None) -> SettingOption:
    return SettingOption(value=value)


GENERAL_FIELDS = (
    SettingFieldSpec(
        slug="site_tagline",
        type="text",
        default="",
        metadata=SettingFieldMetadata(max_length=200),
        public=True,
    ),
    SettingFieldSpec(
        slug="site_logo_asset_id",
        type="upload",
        type_sub="single",
        default=None,
        metadata=SettingFieldMetadata(accept=("image/*",)),
        public=True,
    ),
    SettingFieldSpec(
        slug="default_locale",
        type="select",
        type_sub="string",
        default="zh-CN",
        metadata=SettingFieldMetadata(options=(_option("zh-CN"), _option("en-US"))),
        public=True,
    ),
    SettingFieldSpec(
        slug="default_timezone",
        type="text",
        type_sub="timezone",
        default="Asia/Shanghai",
        metadata=SettingFieldMetadata(max_length=50),
        public=True,
    ),
    SettingFieldSpec(slug="maintenance_mode", type="bool", default=False, public=True),
)

SEO_FIELDS = (
    SettingFieldSpec(
        slug="site_name",
        type="text",
        default="aiya",
        metadata=SettingFieldMetadata(max_length=100),
        public=True,
    ),
    SettingFieldSpec(
        slug="default_title_template",
        type="text",
        default="{title} - aiya",
        metadata=SettingFieldMetadata(max_length=200),
        public=True,
    ),
    SettingFieldSpec(
        slug="default_description",
        type="textarea",
        default="",
        metadata=SettingFieldMetadata(rows=4, max_length=300),
        public=True,
    ),
    SettingFieldSpec(
        slug="default_share_image_asset_id",
        type="upload",
        type_sub="single",
        default=None,
        metadata=SettingFieldMetadata(accept=("image/*",)),
        public=True,
    ),
    SettingFieldSpec(
        slug="robots_policy",
        type="select",
        type_sub="string",
        default="index,follow",
        metadata=SettingFieldMetadata(
            options=(
                _option("index,follow"),
                _option("noindex,nofollow"),
                _option("index,nofollow"),
                _option("noindex,follow"),
            )
        ),
        public=True,
    ),
    SettingFieldSpec(
        slug="canonical_host",
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
        type="text",
        default="aiya",
        metadata=SettingFieldMetadata(max_length=100),
        public=True,
    ),
    SettingFieldSpec(slug="email_enabled", type="bool", default=False, public=True),
    SettingFieldSpec(
        slug="default_channel",
        type="select",
        type_sub="string",
        default="email",
        metadata=SettingFieldMetadata(options=(_option("email"),)),
        public=True,
    ),
    SettingFieldSpec(
        slug="email_provider",
        type="select",
        type_sub="string",
        default="email.smtp",
        metadata=SettingFieldMetadata(options=(_option("email.smtp"), _option("email.smtp2go"))),
    ),
    SettingFieldSpec(slug="smtp_enabled", type="bool", default=False),
    SettingFieldSpec(
        slug="smtp_host", type="text", default="", metadata=SettingFieldMetadata(max_length=200)
    ),
    SettingFieldSpec(
        slug="smtp_port",
        type="text",
        type_sub="integer",
        default=25,
        metadata=SettingFieldMetadata(max_length=5),
    ),
    SettingFieldSpec(
        slug="smtp_username", type="text", default="", metadata=SettingFieldMetadata(max_length=200)
    ),
    SettingFieldSpec(
        slug="smtp_password",
        type="text",
        type_sub="password",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        sensitive=True,
    ),
    SettingFieldSpec(
        slug="smtp_from_address",
        type="text",
        type_sub="email",
        default="no-reply@aiya.local",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(slug="smtp_use_tls", type="bool", default=False),
    SettingFieldSpec(slug="smtp_starttls", type="bool", default=False),
    SettingFieldSpec(slug="smtp2go_enabled", type="bool", default=False),
    SettingFieldSpec(
        slug="smtp2go_api_key",
        type="text",
        type_sub="password",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        sensitive=True,
    ),
    SettingFieldSpec(
        slug="smtp2go_region",
        type="select",
        type_sub="string",
        default="global",
        metadata=SettingFieldMetadata(options=(_option("global"), _option("us"), _option("eu"))),
    ),
)

ENTITLEMENTS_FIELDS = (
    SettingFieldSpec(
        slug="registration_reward",
        type="text",
        type_sub="integer",
        default=0,
        metadata=SettingFieldMetadata(max_length=7),
        public=True,
    ),
    SettingFieldSpec(
        slug="invite_reward",
        type="text",
        type_sub="integer",
        default=0,
        metadata=SettingFieldMetadata(max_length=7),
        public=True,
    ),
    SettingFieldSpec(
        slug="gift_quota",
        type="text",
        type_sub="integer",
        default=0,
        metadata=SettingFieldMetadata(max_length=7),
        public=True,
    ),
)

OBJECT_STORAGE_FIELDS = (
    SettingFieldSpec(
        slug="storage_provider",
        type="select",
        type_sub="string",
        default="s3",
        metadata=SettingFieldMetadata(options=(_option("s3"),)),
    ),
    SettingFieldSpec(
        slug="s3_endpoint_url",
        type="text",
        type_sub="url",
        default="",
        metadata=SettingFieldMetadata(max_length=500),
    ),
    SettingFieldSpec(
        slug="s3_virtual_host_url",
        type="text",
        type_sub="url",
        default="",
        metadata=SettingFieldMetadata(max_length=500),
    ),
    SettingFieldSpec(
        slug="s3_public_base_url",
        type="text",
        type_sub="url",
        default="",
        metadata=SettingFieldMetadata(max_length=500),
    ),
    SettingFieldSpec(
        slug="s3_bucket",
        type="text",
        default="aiya-assets",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="s3_avatar_bucket",
        type="text",
        default="aiya-avatars",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="s3_content_bucket",
        type="text",
        default="aiya-content",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="s3_region",
        type="text",
        default="us-east-1",
        metadata=SettingFieldMetadata(max_length=100),
    ),
    SettingFieldSpec(
        slug="s3_addressing_style",
        type="select",
        type_sub="string",
        default="path",
        metadata=SettingFieldMetadata(options=(_option("path"), _option("virtual"))),
    ),
    SettingFieldSpec(
        slug="s3_access_key_id",
        type="text",
        type_sub="password",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        sensitive=True,
    ),
    SettingFieldSpec(
        slug="s3_secret_access_key",
        type="text",
        type_sub="password",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        sensitive=True,
    ),
    SettingFieldSpec(
        slug="content_image_max_edge",
        type="text",
        type_sub="integer",
        default=2560,
        metadata=SettingFieldMetadata(max_length=4),
    ),
    SettingFieldSpec(
        slug="content_image_webp_quality",
        type="text",
        type_sub="integer",
        default=85,
        metadata=SettingFieldMetadata(max_length=3),
    ),
)

OPERATIONS_FIELDS = (
    SettingFieldSpec(
        slug="audit_retention_days",
        type="text",
        type_sub="integer",
        default=30,
        metadata=SettingFieldMetadata(max_length=4),
    ),
)

PAYMENTS_FIELDS = (
    SettingFieldSpec(
        slug="provider",
        type="select",
        type_sub="string",
        default="paypal",
        metadata=SettingFieldMetadata(options=(_option("paypal"), _option("epay"))),
    ),
    SettingFieldSpec(
        slug="paypal_environment",
        type="select",
        type_sub="string",
        default="sandbox",
        metadata=SettingFieldMetadata(options=(_option("sandbox"), _option("production"))),
    ),
    SettingFieldSpec(
        slug="paypal_client_id",
        type="text",
        default="",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="paypal_client_secret",
        type="text",
        type_sub="password",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        sensitive=True,
    ),
    SettingFieldSpec(
        slug="paypal_webhook_id",
        type="text",
        default="",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="epay_gateway_url",
        type="text",
        type_sub="url",
        default="",
        metadata=SettingFieldMetadata(max_length=500),
    ),
    SettingFieldSpec(
        slug="epay_merchant_id",
        type="text",
        default="",
        metadata=SettingFieldMetadata(max_length=200),
    ),
    SettingFieldSpec(
        slug="epay_merchant_key",
        type="text",
        type_sub="password",
        default=None,
        metadata=SettingFieldMetadata(max_length=200),
        sensitive=True,
    ),
    SettingFieldSpec(
        slug="epay_payment_type",
        type="text",
        default="alipay",
        metadata=SettingFieldMetadata(max_length=50),
    ),
)


def build_site_setting_group_specs() -> tuple[SettingGroupSpec, ...]:
    return (
        SettingGroupSpec(
            group_key=GENERAL_GROUP_KEY,
            version="2",
            value_schema=GeneralValueSchema,
            fields=GENERAL_FIELDS,
            update_permission="settings.general.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=SEO_GROUP_KEY,
            version="2",
            value_schema=SeoValueSchema,
            fields=SEO_FIELDS,
            update_permission="settings.seo.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=NOTIFICATION_GROUP_KEY,
            version="2",
            value_schema=NotificationValueSchema,
            fields=NOTIFICATION_FIELDS,
            update_permission="settings.notification.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=ENTITLEMENTS_GROUP_KEY,
            version="2",
            value_schema=EntitlementsValueSchema,
            fields=ENTITLEMENTS_FIELDS,
            update_permission="settings.entitlements.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=OBJECT_STORAGE_GROUP_KEY,
            version="2",
            value_schema=ObjectStorageValueSchema,
            fields=OBJECT_STORAGE_FIELDS,
            update_permission="settings.object_storage.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=OPERATIONS_GROUP_KEY,
            version="2",
            value_schema=OperationsValueSchema,
            fields=OPERATIONS_FIELDS,
            update_permission="settings.operations.update",
            cache_policy="event",
        ),
        SettingGroupSpec(
            group_key=PAYMENTS_GROUP_KEY,
            version="2",
            value_schema=PaymentsValueSchema,
            fields=PAYMENTS_FIELDS,
            update_permission="settings.payments.update",
            cache_policy="event",
        ),
    )
