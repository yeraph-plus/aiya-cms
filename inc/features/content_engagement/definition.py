"""Content engagement feature declaration.

The initial implementation uses synchronous command-time projection; the
feature key reserves the composition boundary for event replay workers.
"""

from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(name="content_engagement", version="1", requires=("content", "engagement"))
