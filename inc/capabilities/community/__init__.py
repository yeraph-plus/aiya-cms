"""Public composition surface for the community capability.

The package owns discussion, post, tag and search-projection facts.  Importing
it defines models and declarations only; database connections, routers and
workers are created by ``inc.api``.
"""

from __future__ import annotations

from inc.capabilities.community.commands import CommandContext
from inc.capabilities.community.diagnostics import CommunityDiagnostics
from inc.capabilities.community.ports import CommunityAuthorPort
from inc.capabilities.community.queries import CommunityQueries
from inc.capabilities.community.types import (
    COMMUNITY_DISCUSSION_STATES,
    COMMUNITY_DISCUSSION_TRANSITIONS,
    COMMUNITY_POST_STATES,
    GENERAL_DISCUSSION_TEMPLATE,
    DiscussionTemplateRegistry,
    DiscussionTemplateSpec,
)

__all__ = [
    "COMMUNITY_DISCUSSION_STATES",
    "COMMUNITY_DISCUSSION_TRANSITIONS",
    "COMMUNITY_POST_STATES",
    "CommunityAuthorPort",
    "CommunityDiagnostics",
    "CommunityQueries",
    "CommandContext",
    "DiscussionTemplateRegistry",
    "DiscussionTemplateSpec",
    "GENERAL_DISCUSSION_TEMPLATE",
]
