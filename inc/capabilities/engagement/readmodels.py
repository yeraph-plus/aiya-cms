"""Composition-safe read-model adapters for the engagement capability.

The projection implementation remains private to the capability.  The
composition root may depend on this public read-model surface when wiring the
content-engagement feature; it must not reach into implementation modules.
"""

from inc.capabilities.engagement.projection import ContentEngagementProjection

__all__ = ["ContentEngagementProjection"]
