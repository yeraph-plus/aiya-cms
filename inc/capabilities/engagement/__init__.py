"""Content engagement facts and projected counters.

The capability owns only engagement tables. Content identity and publication
state are supplied through the ``EngageableContentReader`` port.
"""

from inc.capabilities.engagement.commands import EngagementCommands
from inc.capabilities.engagement.queries import EngagementQueries
from inc.capabilities.engagement.schemas import (
    EngagementSummaryDTO,
    LikeContentInput,
    RateContentInput,
    RecordContentViewInput,
    UnlikeContentInput,
    WithdrawRatingInput,
)

__all__ = [
    "EngagementCommands",
    "EngagementQueries",
    "EngagementSummaryDTO",
    "LikeContentInput",
    "RateContentInput",
    "RecordContentViewInput",
    "UnlikeContentInput",
    "WithdrawRatingInput",
]
