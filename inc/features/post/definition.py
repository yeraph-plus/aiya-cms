"""Post feature: content type and taxonomy dimension declarations.

Contract source: context/spec/features.md §4.1.

Pure-data declarations: the composition root registers these into the
content type registry and the taxonomy dimension registry at boot. post
supports schedule, pin, owner and references; category is single-select
and tag is multi-select.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from inc.capabilities.content import DEFAULT_TRANSITIONS, STANDARD_STATES, ContentTypeSpec
from inc.capabilities.taxonomy import DimensionSpec
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="post", version="1", requires=("assets", "content", "taxonomy"))


class PostData(BaseModel):
    """Validated per-type data payload for post content.

    Tag relationships belong exclusively to the taxonomy tag dimension;
    no duplicate tag list is stored here.
    """

    model_config = ConfigDict(extra="forbid")


content_type_spec = ContentTypeSpec(
    type_name="post",
    version="1",
    display_name="Post",
    data_schema=PostData,
    data_schema_version="1",
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
        dimension_key="category",
        version="1",
        display_name="Category",
        target_types=("post",),
        selection_mode="single",
        min_items=0,
        max_items=1,
        manage_permission="taxonomy.manage",
    ),
    DimensionSpec(
        dimension_key="tag",
        version="1",
        display_name="Tag",
        target_types=("post",),
        selection_mode="multiple",
        min_items=0,
        max_items=10,
        manage_permission="taxonomy.manage",
    ),
)
