"""In-memory metrics registry and provider contract.

Contract source: context/spec/kernel/observability.md §2.

Kernel defines counter/gauge/histogram primitives with low-cardinality
label rules; capabilities declare their own business metrics. A registry is
per-application-container and frozen-aware; it is never a process-global.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

_HIGH_CARDINALITY_LABEL_PATTERNS = (
    "id",
    "user",
    "content",
    "token",
    "url",
    "path",
    "message",
    "email",
    "name",
)


def validate_label_names(label_names: tuple[str, ...]) -> None:
    """Reject label names that imply high-cardinality values."""

    for name in label_names:
        lowered = name.lower()
        if any(pattern in lowered for pattern in _HIGH_CARDINALITY_LABEL_PATTERNS):
            raise ValueError(
                f"label {name!r} is likely high-cardinality; use low-cardinality labels"
            )


def _check_labels(name: str, label_names: tuple[str, ...], labels: dict[str, Any]) -> None:
    missing = [n for n in label_names if n not in labels]
    extra = [n for n in labels if n not in label_names]
    if missing or extra:
        raise ValueError(f"metric {name}: invalid labels missing={missing} extra={extra}")


class MetricSink(Protocol):
    """Receives metric points for export (statsd/prometheus adapters later)."""

    def emit(self, point: MetricPoint) -> None: ...


@dataclass(frozen=True, slots=True)
class MetricPoint:
    name: str
    kind: str
    labels: tuple[tuple[str, str], ...]
    value: float


class MetricRegistry:
    """In-memory counter/gauge/histogram store with deterministic snapshot."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = {}
        self._sinks: list[MetricSink] = []

    def attach(self, sink: MetricSink) -> None:
        self._sinks.append(sink)

    def counter(self, name: str, *, label_names: tuple[str, ...] = ()) -> Counter:
        validate_label_names(label_names)
        return Counter(self, name, label_names)

    def gauge(self, name: str, *, label_names: tuple[str, ...] = ()) -> Gauge:
        validate_label_names(label_names)
        return Gauge(self, name, label_names)

    def histogram(self, name: str, *, label_names: tuple[str, ...] = ()) -> Histogram:
        validate_label_names(label_names)
        return Histogram(self, name, label_names)

    def _key(self, name: str, labels: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
        return name, tuple(sorted(labels.items()))

    def _record_counter(self, name: str, labels: dict[str, str], amount: float) -> None:
        key = self._key(name, labels)
        self._counters[key] = self._counters.get(key, 0.0) + amount
        self._emit(MetricPoint(name, "counter", key[1], self._counters[key]))

    def _record_gauge(self, name: str, labels: dict[str, str], value: float) -> None:
        key = self._key(name, labels)
        self._gauges[key] = value
        self._emit(MetricPoint(name, "gauge", key[1], value))

    def _record_histogram(self, name: str, labels: dict[str, str], value: float) -> None:
        key = self._key(name, labels)
        self._histograms.setdefault(key, []).append(value)
        self._emit(MetricPoint(name, "histogram", key[1], value))

    def _emit(self, point: MetricPoint) -> None:
        for sink in self._sinks:
            sink.emit(point)

    def snapshot(self) -> tuple[MetricPoint, ...]:
        collected: list[MetricPoint] = []
        for key, value in self._counters.items():
            collected.append(MetricPoint(key[0], "counter", key[1], value))
        for key, value in self._gauges.items():
            collected.append(MetricPoint(key[0], "gauge", key[1], value))
        for key, values in self._histograms.items():
            collected.append(MetricPoint(key[0], "histogram", key[1], float(len(values))))
        return tuple(sorted(collected, key=lambda p: (p.name, p.labels, p.kind)))

    def clear(self) -> None:
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()


class Counter:
    def __init__(self, registry: MetricRegistry, name: str, label_names: tuple[str, ...]) -> None:
        self._registry = registry
        self._name = name
        self._label_names = label_names

    def inc(self, amount: float = 1.0, **labels: Any) -> None:
        _check_labels(self._name, self._label_names, labels)
        self._registry._record_counter(self._name, dict(labels), amount)  # noqa: SLF001


class Gauge:
    def __init__(self, registry: MetricRegistry, name: str, label_names: tuple[str, ...]) -> None:
        self._registry = registry
        self._name = name
        self._label_names = label_names

    def set(self, value: float, **labels: Any) -> None:
        _check_labels(self._name, self._label_names, labels)
        self._registry._record_gauge(self._name, dict(labels), value)  # noqa: SLF001


class Histogram:
    def __init__(self, registry: MetricRegistry, name: str, label_names: tuple[str, ...]) -> None:
        self._registry = registry
        self._name = name
        self._label_names = label_names

    def observe(self, value: float, **labels: Any) -> None:
        _check_labels(self._name, self._label_names, labels)
        self._registry._record_histogram(self._name, dict(labels), value)  # noqa: SLF001
