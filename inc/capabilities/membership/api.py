"""Public membership administration surface.

ORM models remain private to the capability implementation; HTTP composition
uses the semantic service exported here instead of persistence types.
"""

from __future__ import annotations

from inc.capabilities.membership.admin import MembershipAdminService

__all__ = ["MembershipAdminService"]
