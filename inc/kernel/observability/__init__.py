"""Observability: logging, metrics, diagnostics, audit and health contracts.

Contract source: context/spec/kernel/observability.md.
"""

from __future__ import annotations

from inc.kernel.observability.audit import AuditEnvelope, AuditWriter
from inc.kernel.observability.diagnostics import (
    AdminSummaryProvider,
    AdminSummaryRegistry,
    DiagnosticProvider,
    DiagnosticRegistry,
    DiagnosticResult,
    DiagnosticStatus,
)
from inc.kernel.observability.logging import configure_logging, get_logger
from inc.kernel.observability.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricPoint,
    MetricRegistry,
    MetricSink,
    validate_label_names,
)

__all__ = [
    "AdminSummaryProvider",
    "AdminSummaryRegistry",
    "AuditEnvelope",
    "AuditWriter",
    "Counter",
    "DiagnosticProvider",
    "DiagnosticRegistry",
    "DiagnosticResult",
    "DiagnosticStatus",
    "Gauge",
    "Histogram",
    "MetricPoint",
    "MetricRegistry",
    "MetricSink",
    "configure_logging",
    "get_logger",
    "validate_label_names",
]
