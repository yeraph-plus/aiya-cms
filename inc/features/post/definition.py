"""Pure-data declaration of the post feature."""

from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="post", version="1", requires=("content", "taxonomy"))
