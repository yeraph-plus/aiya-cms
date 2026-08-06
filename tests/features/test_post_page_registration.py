"""Post/page feature registration acceptance.

Contract source: context/spec/features.md §4/§7.

post registers the post content type plus category (single) and tag
(multiple) dimensions; page registers only a content type and no
taxonomy. Both reuse capability declarations without duplicating ORM or
services.
"""

from __future__ import annotations


def test_post_declares_type_and_dimensions() -> None:
    from inc.features.page.definition import content_type_spec as page_spec
    from inc.features.post.definition import content_type_spec as post_spec
    from inc.features.post.definition import dimension_specs

    assert post_spec.type_name == "post"
    assert post_spec.allows_schedule and post_spec.allows_pin
    assert post_spec.allows_references
    assert post_spec.default_state == "draft"

    keys = [d.dimension_key for d in dimension_specs]
    assert keys == ["category", "tag"]
    category = dimension_specs[0]
    tag = dimension_specs[1]
    assert category.selection_mode == "single" and category.max_items == 1
    assert tag.selection_mode == "multiple" and tag.max_items == 10
    assert all("post" in d.target_types for d in dimension_specs)

    assert page_spec.type_name == "page"
    assert page_spec.allows_schedule and page_spec.allows_pin
    assert not page_spec.allows_references


def test_page_declares_no_dimensions() -> None:
    import inc.features.page.definition as page

    assert not hasattr(page, "dimension_specs")
    assert not hasattr(page, "content_type_spec") or page.content_type_spec is not None
