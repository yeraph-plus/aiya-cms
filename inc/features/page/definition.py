"""Page v2 content product declarations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from inc.capabilities.content import DEFAULT_TRANSITIONS, STANDARD_STATES, ContentTypeSpec
from inc.capabilities.taxonomy import DimensionSpec
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="page", version="2", requires=("assets", "content", "taxonomy"))


class SeoDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=300)


class PageDataV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    section: str | None = Field(default=None, max_length=100)
    seo: SeoDataV1 | None = None


content_type_spec = ContentTypeSpec(
    type_name="page",
    version="2",
    display_name="Page",
    data_schema=PageDataV2,
    data_schema_version="2",
    allowed_states=STANDARD_STATES,
    default_state="draft",
    transitions=DEFAULT_TRANSITIONS,
    allows_schedule=True,
    allows_pin=True,
    allows_owner=True,
    allows_references=False,
    allows_incoming_references=False,
    title_max_length=200,
    body_max_bytes=524288,
    excerpt_max_length=300,
    requires_ready_markdown_assets=True,
    publication_policy_key="assets.ready_markdown.v1",
)

dimension_specs = (
    DimensionSpec(
        dimension_key="page.category",
        version="2",
        display_name="Category",
        target_types=("page",),
        selection_mode="single",
        min_items=1,
        max_items=1,
    ),
)
