"""Pure-data declaration of the check_in feature."""

from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="check_in", version="1", requires=("points",))
