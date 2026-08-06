"""SEO settings group.

Contract source: context/spec/capabilities/settings.md §5.

Structured site defaults only: the backend never stores frontend routes,
page trees or per-page rendering rules. The share image is an opaque asset
reference.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from inc.capabilities.settings.groups import SettingGroupSpec

SEO_GROUP_KEY = "seo"


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


def build_seo_group_spec() -> SettingGroupSpec:
    return SettingGroupSpec(
        group_key=SEO_GROUP_KEY,
        version="1",
        value_schema=SeoValueSchema,
        public_fields=SEO_PUBLIC_FIELDS,
        update_permission="settings.seo.update",
        cache_policy="event",
    )
