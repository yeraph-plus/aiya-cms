"""Kernel-owned polymorphic comment primitives."""

from .errors import (
    COMMENT_001,
    COMMENT_002,
    COMMENT_003,
    COMMENT_004,
    COMMENT_005,
    COMMENT_006,
    COMMENT_CODES,
)
from .events import COMMENT_EVENT_TYPES, CommentEventPayload, CommentModeratedPayload
from .models import Comment, CommentExtra, CommentStatus
from .repositories import CommentRepository
from .schemas import (
    SLOT_COMMENT_STATS,
    CommentCreate,
    CommentModerationQuery,
    CommentRead,
    CommentStats,
    CommentStatsDTO,
    CommentThread,
    CommentThreadQuery,
    CommentUpdate,
    ModerateAction,
    ModerateRequest,
)
from .services import CommentService
from .targets import CommentTargetPolicy, TargetExists, TargetPolicyResolver
from .uow import CommentUnitOfWork
from .wiring import COMMENT_PIPELINE_KEYS, COMMENT_SLOT_KEYS, register_events, register_pipelines

__all__ = [
    "Comment",
    "CommentExtra",
    "CommentStatus",
    "CommentCreate",
    "CommentModerationQuery",
    "CommentUpdate",
    "CommentRead",
    "CommentThread",
    "CommentThreadQuery",
    "CommentStats",
    "CommentStatsDTO",
    "ModerateAction",
    "ModerateRequest",
    "SLOT_COMMENT_STATS",
    "CommentService",
    "CommentTargetPolicy",
    "TargetExists",
    "TargetPolicyResolver",
    "CommentRepository",
    "CommentUnitOfWork",
    "CommentEventPayload",
    "CommentModeratedPayload",
    "COMMENT_EVENT_TYPES",
    "COMMENT_PIPELINE_KEYS",
    "COMMENT_SLOT_KEYS",
    "COMMENT_001",
    "COMMENT_002",
    "COMMENT_003",
    "COMMENT_004",
    "COMMENT_005",
    "COMMENT_006",
    "COMMENT_CODES",
    "register_events",
    "register_pipelines",
]
