"""Content-bucket feature declaration."""

from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="content_bucket", version="1", requires=("assets", "settings"))
