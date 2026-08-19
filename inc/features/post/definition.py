"""Post v2 content product declarations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from inc.capabilities.content import DEFAULT_TRANSITIONS, STANDARD_STATES, ContentTypeSpec
from inc.capabilities.taxonomy import DimensionSpec
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(
    name="post",
    version="2",
    requires=("assets", "comments", "content", "engagement", "taxonomy"),
)


class SeoDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=300)


class PostDataV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    seo: SeoDataV1 | None = None


content_type_spec = ContentTypeSpec(
    type_name="post",
    version="2",
    display_name="Post",
    data_schema=PostDataV2,
    data_schema_version="2",
    allowed_states=STANDARD_STATES,
    default_state="draft",
    transitions=DEFAULT_TRANSITIONS,
    allows_schedule=True,
    allows_pin=True,
    allows_owner=True,
    allows_references=True,
    title_max_length=200,
    body_max_bytes=524288,
    excerpt_max_length=300,
    requires_ready_markdown_assets=True,
    publication_policy_key="assets.ready_markdown.v1",
)

dimension_specs = (
    DimensionSpec(
        dimension_key="post.category",
        version="2",
        display_name="Category",
        target_types=("post",),
        selection_mode="single",
        min_items=1,
        max_items=1,
    ),
    DimensionSpec(
        dimension_key="post.tag",
        version="2",
        display_name="Tag",
        target_types=("post",),
        selection_mode="multiple",
        min_items=0,
        max_items=8,
    ),
)

comments_target_policy = "post"
engagement_actions = ("view", "like", "favorite", "rating")
