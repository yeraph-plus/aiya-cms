"""Community capability declaration."""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="community",
    schema_version="1",
    requires=("audit",),
    access_keys=(
        "community.discussions.create",
        "community.discussions.reply",
        "community.discussions.edit_own",
        "community.discussions.moderate",
        "community.discussions.lock",
        "community.discussions.archive",
        "community.posts.moderate",
        "community.tags.manage",
        "community.read_admin",
        "community.search.rebuild",
        "community.purge",
    ),
)
