"""Audit capability: immutable security facts and queries.

Contract source: context/spec/capabilities/audit.md.

Kernel provides the AuditEnvelope shape and durable outbox; audit owns
persistence, deduplication and queries. Producers never import this package:
they append ``audit.entry.recorded.v1`` envelopes through the kernel
OutboxWriter, and the boot-time schema registry validates the payload.
"""

from __future__ import annotations

from inc.kernel.boot import CapabilitySpec

spec = CapabilitySpec(
    name="audit",
    schema_version="1",
    access_keys=("audit.read", "audit.export"),
)
