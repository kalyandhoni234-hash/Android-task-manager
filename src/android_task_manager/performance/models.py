"""Advanced performance & root-cause intelligence — domain models.

This module defines the typed evidence-first vocabulary for v0.9.0. It is
GUI-independent, ADB-independent and deterministic.

The single most important honesty rule of the layer lives here:
``PerformanceEvidence.statement`` is always a literal restatement of observed,
collected numbers (averages, occupancies, sustained spans). It never contains
a root-cause claim ("because the app is leaking memory") — that belongs to a
later, explicitly-gated reasoning stage. A finding is only ever a bundle of
evidence plus a recommended *investigation* action drawn from the existing,
verified action vocabulary.

Reuse policy
------------
* ``DiagnosticFinding`` / ``DiagnosticSeverity`` / ``DiagnosticCategory`` are
  imported from :mod:`android_task_manager.diagnostics.models` and re-exported
  here. The performance layer does **not** redefine the finding contract —
  it produces the same structured findings the diagnostics engine does.
* ``TrendDirection`` and the statistics vocabulary come from
  :mod:`android_task_manager.history.metrics`; ``PerformanceWindow`` and
  ``Baseline`` build on top of those primitives rather than reimplementing
  min/max/avg/trend.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from ..diagnostics.models import (
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticSeverity,
)
from ..history.metrics import TrendDirection

__all__ = [
    "DiagnosticCategory",
    "DiagnosticFinding",
    "DiagnosticSeverity",
    "EvidenceKind",
    "PerformanceEvidence",
    "PerformanceMetric",
    "PerformanceSample",
    "TrendDirection",
]


class PerformanceMetric(str, Enum):
    """Canonical metric keys tracked across a performance session.

    The four live-dashboard metrics reuse the exact ``history`` keys so a
    ``PerformanceWindow`` can share a vocabulary with ``SessionHistory``; the
    extended keys (process count, network throughput) are new but follow the
    same ``str``-keyed ``MetricHistory`` convention.
    """

    CPU = "cpu"
    MEMORY = "memory"
    BATTERY = "battery"
    STORAGE = "storage"
    PROCESS_COUNT = "process_count"
    NETWORK_RX = "network_rx_bytes_per_s"
    NETWORK_TX = "network_tx_bytes_per_s"

    @property
    def is_canonical(self) -> bool:
        return self in _CANONICAL_METRICS


_CANONICAL_METRICS = {
    PerformanceMetric.CPU,
    PerformanceMetric.MEMORY,
    PerformanceMetric.BATTERY,
    PerformanceMetric.STORAGE,
}


class EvidenceKind(str, Enum):
    """What category of observable a piece of evidence represents."""

    STATISTIC = "statistic"
    THRESHOLD_OCCUPANCY = "threshold_occupancy"
    SUSTAINED_THRESHOLD = "sustained_threshold"
    TREND = "trend"
    DELTA = "delta"
    BASELINE_DEVIATION = "baseline_deviation"
    PROCESS_PRESSURE = "process_pressure"
    APPLICATION_PRESSURE = "application_pressure"
    ANOMALY = "anomaly"


@dataclass(frozen=True)
class PerformanceSample:
    """One timestamped, multi-metric observation.

    A ``PerformanceSample`` is the smallest analysis unit: it carries every
    metric observed at a single instant. Metrics that were unavailable at
    that instant are simply absent from ``metrics`` — never fabricated.
    """

    timestamp: float
    metrics: Mapping[str, float] = field(default_factory=dict)

    def available_metrics(self) -> tuple[str, ...]:
        """Metric keys present in this sample (deterministic order)."""
        return tuple(sorted(self.metrics))

    def get(self, metric: str) -> float | None:
        return self.metrics.get(metric)


@dataclass(frozen=True)
class PerformanceEvidence:
    """One observable fact, traceable to collected numbers.

    ``statement`` is the contract: a human-readable sentence built only from
    the literal values passed in (``value``, ``threshold``, ``duration``,
    ``sample_count``). It never asserts a cause.
    """

    evidence_id: str
    timestamp: float
    kind: EvidenceKind
    statement: str
    metric: str | None = None
    value: float | None = None
    threshold: float | None = None
    duration: float | None = None
    sample_count: int | None = None
    entity: str | None = None

    def references_metric(self, metric: str) -> bool:
        return self.metric == metric or self.entity == metric
