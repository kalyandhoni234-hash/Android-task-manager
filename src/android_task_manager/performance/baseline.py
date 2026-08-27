"""Deterministic performance baselines.

A baseline is a small, explainable statistical profile of one metric over a
reference window (the "normal" period). It is computed from concrete samples
only — never inferred.

Reuse
-----
``mean`` / ``minimum`` / ``maximum`` are taken from the existing
:class:`android_task_manager.history.metrics.MetricStats` so the baseline and
the live window never disagree about the average. The quantities ``history``
does not define — ``median``, ``p95`` and ``stddev`` — are added here with the
standard library ``statistics`` module, on plain ``float`` sequences.

All baselines are deterministic: identical inputs always yield an identical
``Baseline``.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from ..history.metrics import MetricStats
from .window import PerformanceWindow

#: Minimum samples before a standard deviation / percentile is meaningful.
_MIN_BASELINE_SAMPLES = 2


@dataclass(frozen=True)
class Baseline:
    """A deterministic statistical profile of one metric."""

    metric: str
    count: int
    mean: float
    median: float
    p95: float
    minimum: float
    maximum: float
    stddev: float | None
    computed_at: float | None = None

    @property
    def has_dispersion(self) -> bool:
        """True when stddev was computed (>= 2 samples)."""
        return self.stddev is not None

    def is_within(self, value: float, k: float = 2.0) -> bool | None:
        """True when *value* is within *k* stddevs of the mean (None when no
        dispersion data)."""
        if self.stddev is None:
            return None
        return abs(value - self.mean) <= k * self.stddev


class BaselineCalculator:
    """Pure baseline math over sample sequences or a window metric."""

    @staticmethod
    def _percentile(sorted_values: list[float], q: float) -> float:
        """Nearest-rank percentile (deterministic, no interpolation)."""
        if not sorted_values:
            raise ValueError("cannot compute percentile of empty sequence")
        rank = math.ceil(q * len(sorted_values))
        rank = max(1, min(len(sorted_values), rank))
        return sorted_values[rank - 1]

    @classmethod
    def from_values(
        cls, metric: str, values: list[float], computed_at: float | None = None
    ) -> Baseline:
        if not values:
            raise ValueError("cannot build a baseline from zero samples")
        ordered = sorted(values)
        mean = sum(ordered) / len(ordered)
        stddev = (
            statistics.pstdev(ordered) if len(ordered) >= _MIN_BASELINE_SAMPLES else None
        )
        return Baseline(
            metric=metric,
            count=len(ordered),
            mean=mean,
            median=statistics.median(ordered),
            p95=cls._percentile(ordered, 0.95),
            minimum=ordered[0],
            maximum=ordered[-1],
            stddev=stddev,
            computed_at=computed_at,
        )

    @classmethod
    def from_window(
        cls, metric: str, window: PerformanceWindow, computed_at: float | None = None
    ) -> Baseline:
        """Build a baseline from one metric's window history.

        mean/min/max come from the shared ``MetricStats``; median/p95/stddev
        are computed here. This guarantees the baseline ``mean`` equals the
        live window ``average``.
        """
        stats: MetricStats = window.stats(metric)
        if stats.count == 0:
            raise ValueError(f"cannot build a baseline from empty metric: {metric!r}")
        ordered = sorted(window.values(metric))
        stddev = (
            statistics.pstdev(ordered) if len(ordered) >= _MIN_BASELINE_SAMPLES else None
        )
        return Baseline(
            metric=metric,
            count=stats.count,
            mean=stats.average or 0.0,
            median=statistics.median(ordered),
            p95=cls._percentile(ordered, 0.95),
            minimum=stats.minimum if stats.minimum is not None else ordered[0],
            maximum=stats.maximum if stats.maximum is not None else ordered[-1],
            stddev=stddev,
            computed_at=computed_at,
        )

    @staticmethod
    def deviation(value: float, baseline: Baseline) -> float:
        """Absolute offset of *value* from the baseline mean."""
        return value - baseline.mean

    @staticmethod
    def zscore(value: float, baseline: Baseline) -> float | None:
        """Signed number of standard deviations from the mean (None without
        dispersion data)."""
        if baseline.stddev is None or baseline.stddev == 0.0:
            return None
        return (value - baseline.mean) / baseline.stddev

    @staticmethod
    def rate_of_change(values: list[float]) -> float | None:
        """Relative change of the last versus the first value.

        ``(last - first) / max(|first|, 1)``; None when fewer than two
        samples. Positive means rising.
        """
        if len(values) < 2:
            return None
        first, last = values[0], values[-1]
        if first == 0.0:
            return 0.0 if last == 0.0 else 1.0 if last > 0 else -1.0
        return (last - first) / abs(first)


__all__ = ["Baseline", "BaselineCalculator"]
