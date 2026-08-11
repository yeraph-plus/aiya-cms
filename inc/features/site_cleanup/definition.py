"""Site cleanup feature declaration."""

from __future__ import annotations

from inc.kernel.boot import FeatureSpec

RETENTION_CRON_KEY = "site.cleanup.retention.v1"

spec = FeatureSpec(
    name="site_cleanup",
    version="1",
    requires=("settings", "audit"),
)
