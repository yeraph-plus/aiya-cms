"""Work content type feature registration contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def _file(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "archive_item_id": "archive-item-b",
        "display_name": "part-b.zip",
        "part_number": 2,
        "size_bytes": 1024,
        "checksum": "sha256:abc",
    }
    value.update(overrides)
    return value


def test_work_declares_type_dependencies_and_namespaced_dimensions() -> None:
    from inc.features.work.definition import content_type_spec, dimension_specs, spec

    assert spec.version == "1"
    assert spec.requires == (
        "archive",
        "assets",
        "comments",
        "content",
        "engagement",
        "taxonomy",
    )
    assert content_type_spec.type_name == "work"
    assert content_type_spec.version == "1"
    assert content_type_spec.data_schema_version == "1"
    assert content_type_spec.body_profile == "gfm-v1"

    expected = (
        ("work.category", "single", 1, 1),
        ("work.source", "multiple", 0, 8),
        ("work.creator", "multiple", 1, 16),
        ("work.group", "multiple", 0, 8),
        ("work.character", "multiple", 0, 32),
        ("work.language", "multiple", 1, 4),
        ("work.genre", "multiple", 0, 32),
        ("work.format", "multiple", 0, 4),
    )
    assert (
        tuple(
            (item.dimension_key, item.selection_mode, item.min_items, item.max_items)
            for item in dimension_specs
        )
        == expected
    )
    assert all(item.target_types == ("work",) for item in dimension_specs)


def test_work_data_is_strict_secret_free_and_stably_sorted() -> None:
    from inc.features.work.definition import WorkDataV1

    data = WorkDataV1.model_validate(
        {
            "alternate_titles": ["Alternate"],
            "cover_asset_id": "asset-1",
            "archive_manifest_version": 3,
            "download_files": [
                _file(),
                _file(
                    archive_item_id="archive-item-a",
                    display_name="part-a.zip",
                    part_number=1,
                    checksum=None,
                ),
            ],
        }
    )
    assert [(item.part_number, item.archive_item_id) for item in data.download_files] == [
        (1, "archive-item-a"),
        (2, "archive-item-b"),
    ]

    forbidden = ("provider_key", "path", "token", "url", "headers")
    for field in forbidden:
        with pytest.raises(ValidationError):
            WorkDataV1.model_validate(
                {
                    "alternate_titles": [],
                    "cover_asset_id": "asset-1",
                    "archive_manifest_version": 1,
                    "download_files": [_file(**{field: "secret"})],
                }
            )

        with pytest.raises(ValidationError):
            WorkDataV1.model_validate(
                {
                    "alternate_titles": [],
                    "cover_asset_id": "asset-1",
                    "archive_manifest_version": 1,
                    "download_files": [],
                    field: "secret",
                }
            )

    with pytest.raises(ValidationError):
        WorkDataV1.model_validate(
            {
                "alternate_titles": [],
                "cover_asset_id": "asset-1",
                "archive_manifest_version": 1,
                "download_files": [_file(archive_item_id="https://provider.invalid/file")],
            }
        )

    with pytest.raises(ValidationError):
        WorkDataV1.model_validate(
            {
                "alternate_titles": [],
                "cover_asset_id": "asset-1",
                "archive_manifest_version": "1",
                "download_files": [],
            }
        )


def test_work_download_profile_enforces_four_gibibyte_limit_in_schema() -> None:
    from inc.features.work.definition import ARCHIVE_PART_MAX_BYTES, WorkDownloadFileV1

    assert ARCHIVE_PART_MAX_BYTES == 4 * 1024 * 1024 * 1024
    size_schema = WorkDownloadFileV1.model_json_schema()["properties"]["size_bytes"]
    assert size_schema["exclusiveMinimum"] == 0
    assert size_schema["maximum"] == ARCHIVE_PART_MAX_BYTES

    with pytest.raises(ValidationError):
        WorkDownloadFileV1.model_validate(_file(size_bytes=ARCHIVE_PART_MAX_BYTES + 1))
