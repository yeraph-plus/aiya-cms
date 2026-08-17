"""Cross-capability authentication workflows.

Registration and password reset are intentionally a feature: identity owns
the atomic user/challenge commands, access owns role projection, and
notification owns out-of-band delivery.  The API router only adapts HTTP to
this gateway.
"""

from __future__ import annotations

from inc.kernel.boot import FeatureSpec

spec = FeatureSpec(
    name="auth",
    version="1",
    requires=("identity", "access", "notification"),
)
