"""Declarative post content type."""

from inc.kernel.content import (
    CommentPolicy,
    ContentStatusDef,
    ContentTransitionDef,
    ContentType,
    TaxonomyGroupDef,
)


class PostContentType(ContentType):
    type_name = "post"
    statuses = (
        ContentStatusDef(slug="draft"),
        ContentStatusDef(slug="pending"),
        ContentStatusDef(slug="published", is_public=True),
    )
    default_status = "draft"
    transitions = (
        ContentTransitionDef(
            action="publish",
            from_statuses=("draft", "pending"),
            to_status="published",
            capability="content:publish",
        ),
        ContentTransitionDef(
            action="unpublish",
            from_statuses=("published",),
            to_status="draft",
            capability="content:publish",
        ),
    )
    fields = ()
    taxonomy_groups = (
        TaxonomyGroupDef(slug="category", title="Category"),
        TaxonomyGroupDef(slug="tag", title="Tag"),
    )
    comment_policy = CommentPolicy(max_depth=3, auto_approve=True, rate_limit=10)
