"""Post/page content type feature registration contracts."""

from __future__ import annotations


def test_post_declares_type_and_dimensions() -> None:
    from inc.features.post.definition import content_type_spec, dimension_specs, spec

    assert spec.version == "2"
    assert spec.requires == ("assets", "comments", "content", "engagement", "taxonomy")
    assert content_type_spec.type_name == "post"
    assert content_type_spec.version == "2"
    assert content_type_spec.body_profile == "gfm-v1"
    assert content_type_spec.allows_schedule and content_type_spec.allows_pin
    assert content_type_spec.allows_references
    assert content_type_spec.default_state == "draft"

    keys = [d.dimension_key for d in dimension_specs]
    assert keys == ["post.category", "post.tag"]
    category = dimension_specs[0]
    tag = dimension_specs[1]
    assert (category.selection_mode, category.min_items, category.max_items) == ("single", 1, 1)
    assert (tag.selection_mode, tag.min_items, tag.max_items) == ("multiple", 0, 8)
    assert all("post" in d.target_types for d in dimension_specs)

    from inc.features.post import definition as post

    assert post.comments_target_policy == "post"
    assert post.engagement_actions == ("view", "like", "favorite", "rating")
    assert not hasattr(post, "archive_manifest_profile")


def test_page_declares_only_category_and_no_extra_surface() -> None:
    import inc.features.page.definition as page

    assert page.spec.version == "2"
    assert page.spec.requires == ("assets", "content", "taxonomy")
    assert page.content_type_spec.type_name == "page"
    assert page.content_type_spec.version == "2"
    assert page.content_type_spec.body_profile == "gfm-v1"
    assert page.content_type_spec.allows_schedule and page.content_type_spec.allows_pin
    assert not page.content_type_spec.allows_references

    assert len(page.dimension_specs) == 1
    category = page.dimension_specs[0]
    assert category.dimension_key == "page.category"
    assert category.target_types == ("page",)
    assert (category.selection_mode, category.min_items, category.max_items) == ("single", 1, 1)

    forbidden_surface = (
        "comments_target_policy",
        "engagement_actions",
        "archive_manifest_profile",
        "download_files",
        "favorite_policy",
        "rating_policy",
    )
    assert all(not hasattr(page, name) for name in forbidden_surface)
