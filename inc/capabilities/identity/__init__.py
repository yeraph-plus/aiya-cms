"""Identity capability: user subjects, login identifiers, credentials.

Contract source: context/spec/capabilities/identity.md.

Public surface for the composition root and HTTP layer: queries, the
credential authenticator, command context and diagnostics.
"""

from __future__ import annotations

from inc.capabilities.identity.commands import CommandContext, UpdateProfile
from inc.capabilities.identity.diagnostics import IdentityDiagnostics
from inc.capabilities.identity.queries import CredentialAuthenticator, IdentityQueries
from inc.capabilities.identity.schemas import SubjectDTO, UpdateProfileInput

__all__ = [
    "CommandContext",
    "CredentialAuthenticator",
    "IdentityDiagnostics",
    "IdentityQueries",
    "SubjectDTO",
    "UpdateProfile",
    "UpdateProfileInput",
]
