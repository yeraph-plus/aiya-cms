"""Kernel-owned taxonomy primitives."""

from .errors import TERM_001, TERM_002, TERM_003, TERM_004, TERM_005, TERM_CODES
from .events import TAXONOMY_EVENT_TYPES, TermAssignedPayload, TermEventPayload
from .models import Term, TermData, TermRelationship
from .repositories import TermRelationshipRepository, TermRepository
from .schemas import (
    ContentTerms,
    ContentTermsDTO,
    TermAssign,
    TermCreate,
    TermListQuery,
    TermRead,
    TermUpdate,
)
from .services import TermService
from .uow import TaxonomyUnitOfWork
from .wiring import (
    TAXONOMY_PIPELINE_KEYS,
    TAXONOMY_SLOT_KEYS,
    register_events,
    register_pipelines,
)

__all__ = [
    "TERM_001",
    "TERM_002",
    "TERM_003",
    "TERM_004",
    "TERM_005",
    "TERM_CODES",
    "TAXONOMY_EVENT_TYPES",
    "TAXONOMY_PIPELINE_KEYS",
    "TAXONOMY_SLOT_KEYS",
    "Term",
    "TermData",
    "TermRelationship",
    "TermRepository",
    "TermRelationshipRepository",
    "TermService",
    "TaxonomyUnitOfWork",
    "TermCreate",
    "TermUpdate",
    "TermRead",
    "TermAssign",
    "TermListQuery",
    "ContentTerms",
    "ContentTermsDTO",
    "TermEventPayload",
    "TermAssignedPayload",
    "register_events",
    "register_pipelines",
]
