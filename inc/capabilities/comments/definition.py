"""Comments capability declaration."""

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="comments",
    schema_version="1",
    access_keys=(
        "comments.read",
        "comments.submit",
        "comments.moderate",
        "comments.delete",
    ),
)
