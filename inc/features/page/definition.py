"""Pure-data declaration of the page feature."""

from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="page", version="1", requires=("content",))
