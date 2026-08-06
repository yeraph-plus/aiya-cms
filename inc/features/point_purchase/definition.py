"""Pure-data declaration of the point_purchase feature."""

from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="point_purchase", version="1", requires=("payments", "points"))
