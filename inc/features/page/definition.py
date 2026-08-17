"""Page feature: content type declaration only.

Contract source: context/spec/features.md §4.2.

page registers no taxonomy dimension and no parent-child pages; it reuses
content's draft/publish/schedule/archive/pin capabilities. Frontend owns
routing and per-page SEO composition.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from inc.capabilities.content import DEFAULT_TRANSITIONS, STANDARD_STATES, ContentTypeSpec
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="page", version="1", requires=("assets", "content"))


class PageData(BaseModel):
    """Validated per-type data payload for page content."""

    model_config = ConfigDict(extra="forbid")

    section: str | None = Field(default=None, max_length=100)


content_type_spec = ContentTypeSpec(
    type_name="page",
    version="1",
    display_name="Page",
    data_schema=PageData,
    data_schema_version="1",
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
