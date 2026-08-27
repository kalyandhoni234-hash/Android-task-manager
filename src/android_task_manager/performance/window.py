"""Bounded performance window over time with deterministic statistics.

A :class:`PerformanceWindow` is a fixed-size collection of
:class:`PerformanceSample` observations. Rather than reimplementing
min/max/avg/trend/peak logic, it maintains one
:class:`android_task_manager.history.metrics.MetricHistory` per metric and
delegates the deterministic statistics to it. The window therefore inherits
the existing, tested guarantees:

* unavailable (``None``) values are never recorded;
* consecutive duplicate values are deduped;
* the window is bounded — memory growth is capped;
* trend direction is explainable and ``INSUFFICIENT`` when under-sampled.

New, window-level quantities that ``history`` does not define — threshold
occupancy (fraction of samples above a bound) and change-from-baseline — are
added here, computed from the same underlying samples.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from ..history.metrics import MetricHistory, MetricStats, PeakPeriod, TrendDirection
from .models import PerformanceSample

#: Default bound for an extended-metric window (process count / network).
DEFAULT_MAX_SAMPLES = 600


class PerformanceWindow:
    """A bounded, multi-metric observation window."""

    def __init__(
        self,
        max_samples: int = DEFAULT_MAX_SAMPLES,
        metrics: Iterable[str] | None = None,
    ) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be >= 1")
        self._max_samples = max_samples
        self._samples: deque[PerformanceSample] = deque(maxlen=max_samples)
        self._histories: dict[str, MetricHistory] = {}
        for metric in metrics or ():
            self._histories[metric] = MetricHistory(max_samples=max_samples)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def add(self, sample: PerformanceSample) -> None:
        """Record one sample; per-metric histories are fed the available
        values. Unavailable metrics are skipped (never fabricated)."""
        if not sample.metrics:
            return
        self._samples.append(sample)
        for key, value in sample.metrics.items():
            history = self._histories.get(key)
            if history is None:
                history = MetricHistory(max_samples=self._max_samples)
                self._histories[key] = history
            history.add_sample(value, sample.timestamp)

    def clear(self) -> None:
        """Drop every sample and reset the per-metric histories."""
        self._samples.clear()
        for history in self._histories.values():
            history.clear()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    @property
    def max_samples(self) -> int:
        return self._max_samples

    @property
    def is_empty(self) -> bool:
        return not self._samples

    def __len__(self) -> int:
        return len(self._samples)

    def metrics(self) -> tuple[str, ...]:
        return tuple(self._histories)

    def iter_samples(self) -> tuple[PerformanceSample, ...]:
        return tuple(self._samples)

    def metric_history(self, metric: str) -> MetricHistory:
        """The underlying ``MetricHistory`` for one metric (reuse, not copy)."""
        if metric not in self._histories:
            raise KeyError(f"unknown metric: {metric!r}")
        return self._histories[metric]

    def stats(self, metric: str) -> MetricStats:
        return self.metric_history(metric).stats()

    def average(self, metric: str) -> float | None:
        return self.metric_history(metric).stats().average

    def minimum(self, metric: str) -> float | None:
        return self.metric_history(metric).stats().minimum

    def maximum(self, metric: str) -> float | None:
        return self.metric_history(metric).stats().maximum

    def latest(self, metric: str) -> float | None:
        return self.metric_history(metric).latest()

    def trend(self, metric: str) -> TrendDirection:
        return self.metric_history(metric).stats().trend

    def values(self, metric: str) -> tuple[float, ...]:
        return tuple(s.value for s in self.metric_history(metric))

    def duration(self) -> float | None:
        """Span from first to last sample timestamp (None when < 2)."""
        if len(self._samples) < 2:
            return None
        return self._samples[-1].timestamp - self._samples[0].timestamp

    def threshold_occupancy(self, metric: str, threshold: float) -> float:
        """Fraction of recorded samples at or above *threshold* (0..1).

        Deterministic: ``count(>=threshold) / count``. Returns ``0.0`` for an
        empty window — never a guessed proportion.
        """
        history = self.metric_history(metric)
        if history.is_empty:
            return 0.0
        total = len(history)
        above = sum(1 for s in history if s.value >= threshold)
        return above / total

    def sustained_threshold(
        self, metric: str, threshold: float, duration: float
    ) -> float | None:
        """Earliest timestamp *metric >= threshold* held continuously for
        *duration*, or None (delegates to ``MetricHistory.sustained_since``)."""
        return self.metric_history(metric).sustained_since(threshold, duration)

    def peak_periods(
        self, metric: str, threshold: float, min_samples: int = 2
    ) -> tuple[PeakPeriod, ...]:
        return self.metric_history(metric).peak_periods(threshold, min_samples)

    def change_from_baseline(self, metric: str, baseline_mean: float) -> float | None:
        """Average minus *baseline_mean* for one metric (None when empty)."""
        avg = self.average(metric)
        if avg is None:
            return None
        return avg - baseline_mean


__all__ = ["DEFAULT_MAX_SAMPLES", "PerformanceWindow"]
