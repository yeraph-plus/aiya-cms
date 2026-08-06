"""Audit capability: immutable security facts and queries.

Contract source: context/spec/capabilities/audit.md.

Public surface: the outbox-consumed inbox handler and the read-only
queries.
"""

from __future__ import annotations

from inc.capabilities.audit.service import AuditInboxHandler, AuditQueries

__all__ = ["AuditInboxHandler", "AuditQueries"]
