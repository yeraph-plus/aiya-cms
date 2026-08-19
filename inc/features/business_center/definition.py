"""Business center feature declaration."""

from inc.features.business_center.domain import behavior_specs
from inc.features.business_center.workflows import CONSUME_WORKFLOW_KEY
from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="business_center", version="1", requires=("archive", "points"))

__all__ = ["CONSUME_WORKFLOW_KEY", "behavior_specs", "spec"]
