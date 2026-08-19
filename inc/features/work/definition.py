"""Work v1 content product and archive catalog declarations."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from inc.capabilities.content import DEFAULT_TRANSITIONS, STANDARD_STATES, ContentTypeSpec
from inc.capabilities.taxonomy import DimensionSpec
from inc.kernel.boot import FeatureSpec

ARCHIVE_PART_PROFILE_KEY = "archive.part.4g.v1"
ARCHIVE_PART_MAX_BYTES = 4 * 1024 * 1024 * 1024

spec = FeatureSpec(
    name="work",
    version="1",
    requires=("archive", "assets", "comments", "content", "engagement", "taxonomy"),
)


class SeoDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=300)


class WorkDisplayMetadataV1(BaseModel):
    """Public labels suitable for rendering and indexing."""

    model_config = ConfigDict(extra="forbid", strict=True)

    edition: str | None = Field(default=None, max_length=100)
    publisher: str | None = Field(default=None, max_length=200)
    release_label: str | None = Field(default=None, max_length=100)


class WorkDownloadFileV1(BaseModel):
    """Secret-free public archive item snapshot."""

    model_config = ConfigDict(extra="forbid", strict=True)

    archive_item_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=500)
    part_number: int = Field(gt=0)
    size_bytes: int = Field(gt=0, le=ARCHIVE_PART_MAX_BYTES)
    checksum: str | None = Field(default=None, max_length=300)

    @field_validator("archive_item_id")
    @classmethod
    def _opaque_archive_item_id(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme or value.startswith("//") or any(char in value for char in "\x00\r\n"):
            raise ValueError("archive_item_id must be an opaque reference")
        return value


class WorkDataV1(BaseModel):
    """Strict persisted data schema for a published work catalog."""

    model_config = ConfigDict(extra="forbid", strict=True)

    alternate_titles: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=20
    )
    release_date: date | None = None
    display_metadata: WorkDisplayMetadataV1 | None = None
    seo: SeoDataV1 | None = None
    cover_asset_id: str = Field(min_length=1, max_length=200)
    archive_manifest_version: int = Field(ge=1)
    download_files: list[WorkDownloadFileV1] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _sort_download_files(self) -> WorkDataV1:
        self.download_files.sort(key=lambda item: (item.part_number, item.archive_item_id))
        return self


content_type_spec = ContentTypeSpec(
    type_name="work",
    version="1",
    display_name="Work",
    data_schema=WorkDataV1,
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


def _dimension(key: str, display_name: str, mode: str, minimum: int, maximum: int) -> DimensionSpec:
    return DimensionSpec(
        dimension_key=key,
        version="1",
        display_name=display_name,
        target_types=("work",),
        selection_mode=mode,
        min_items=minimum,
        max_items=maximum,
    )


dimension_specs = (
    _dimension("work.category", "Category", "single", 1, 1),
    _dimension("work.source", "Source", "multiple", 0, 8),
    _dimension("work.creator", "Creator", "multiple", 1, 16),
    _dimension("work.group", "Group", "multiple", 0, 8),
    _dimension("work.character", "Character", "multiple", 0, 32),
    _dimension("work.language", "Language", "multiple", 1, 4),
    _dimension("work.genre", "Genre", "multiple", 0, 32),
    _dimension("work.format", "Format", "multiple", 0, 4),
)

comments_target_policy = "work"
engagement_actions = ("view", "like", "favorite", "rating")
archive_manifest_profile = ARCHIVE_PART_PROFILE_KEY
