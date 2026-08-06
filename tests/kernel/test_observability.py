"""Observability contract tests (observability.md §1/§2/§3/§6)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from inc.kernel.observability import (
    AdminSummaryRegistry,
    AuditEnvelope,
    DiagnosticRegistry,
    DiagnosticResult,
    DiagnosticStatus,
    MetricRegistry,
    configure_logging,
    get_logger,
    validate_label_names,
)
from inc.kernel.observability.logging import _redact_processor


def test_metric_counters_gauges_histograms() -> None:
    registry = MetricRegistry()
    counter = registry.counter("kernel.outbox.delivered")
    counter.inc()
    counter.inc(2)
    gauge = registry.gauge("kernel.tasks.pending", label_names=("queue",))
    gauge.set(3, queue="default")
    histogram = registry.histogram("kernel.http.latency")
    histogram.observe(0.5)
    histogram.observe(1.5)

    snapshot = registry.snapshot()
    assert {p.name for p in snapshot} == {
        "kernel.outbox.delivered",
        "kernel.tasks.pending",
        "kernel.http.latency",
    }
    delivered = next(p for p in snapshot if p.name == "kernel.outbox.delivered")
    assert delivered.value == 3
    pending = next(p for p in snapshot if p.name == "kernel.tasks.pending")
    assert pending.labels == (("queue", "default"),)


def test_metric_label_validation() -> None:
    with pytest.raises(ValueError):
        validate_label_names(("user_id",))
    with pytest.raises(ValueError):
        validate_label_names(("path",))
    validate_label_names(("status", "queue"))


def test_metric_invalid_labels_rejected() -> None:
    registry = MetricRegistry()
    counter = registry.counter("kernel.x", label_names=("status",))
    with pytest.raises(ValueError):
        counter.inc(status="ok", extra="nope")
    with pytest.raises(ValueError):
        counter.inc()  # missing required label


def test_metrics_snapshot_is_deterministic() -> None:
    registry = MetricRegistry()
    for name in ("b.metric", "a.metric", "c.metric"):
        registry.counter(name).inc()
    names = [p.name for p in registry.snapshot()]
    assert names == sorted(names)


def test_diagnostics_aggregate_and_distinguish_failures() -> None:
    registry = DiagnosticRegistry()

    class Healthy:
        key = "healthy"

        async def run(self) -> list[DiagnosticResult]:
            return [
                DiagnosticResult(code="kernel.test.ok", status=DiagnosticStatus.OK, summary="fine")
            ]

    class Broken:
        key = "broken"

        async def run(self) -> list[DiagnosticResult]:
            raise RuntimeError("probe exploded")

    registry.register(Healthy())
    registry.register(Broken())

    import asyncio

    async def collect() -> dict[str, DiagnosticStatus]:
        results = await registry.run_all()
        return {r.code: r.status for r in results}

    statuses = asyncio.run(collect())
    assert statuses["kernel.test.ok"] is DiagnosticStatus.OK
    assert statuses["kernel.diagnostics.broken"] is DiagnosticStatus.UNAVAILABLE

    registry.freeze()
    with pytest.raises(RuntimeError):
        registry.register(Healthy())


def test_admin_summary_registry_isolates_failures() -> None:
    registry = AdminSummaryRegistry()

    class Provider:
        key = "counts"

        async def summary(self) -> dict[str, Any]:
            return {"posts": 3}

    class Broken:
        key = "broken"

        async def summary(self) -> dict[str, Any]:
            raise RuntimeError("nope")

    registry.register(Provider())
    registry.register(Broken())

    import asyncio

    summaries = asyncio.run(registry.run_all())
    assert summaries["counts"] == {"posts": 3}
    assert summaries["broken"] == {"unavailable": True}


def test_audit_envelope_shape() -> None:
    envelope = AuditEnvelope(
        event_key="identity.login.succeeded.v1",
        action="identity.login",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        actor_type="user",
        actor_id="u-1",
        target_type="user",
        target_id="u-1",
        trace_id="t-1",
        details={"method": "password"},
    )
    assert envelope.event_key == "identity.login.succeeded.v1"
    assert envelope.details == {"method": "password"}
    assert envelope.actor_id == "u-1"


def test_redact_processor_masks_secrets() -> None:
    processed = _redact_processor(
        None,
        "info",
        {"password": "hunter2", "client_secret": "s3cret", "kept": "yes"},
    )
    assert processed["password"] == "[REDACTED]"
    assert processed["client_secret"] == "[REDACTED]"
    assert processed["kept"] == "yes"


def test_logging_smoke_with_redaction(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_output=True)
    logger = get_logger("kernel.test")
    logger.info("workflow.step", instance="i-1", step="a", password="hunter2", kept="yes")
    output = capsys.readouterr().out
    assert "hunter2" not in output
    assert "yes" in output
