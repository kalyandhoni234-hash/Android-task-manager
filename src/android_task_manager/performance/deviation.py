"""Baseline deviation model (pure, Qt/ADB-free).

A :class:`MetricDeviation` is a deterministic, explainable description of *how
far* a metric's current reading sits from the device's own observed baseline.

Every quantity is derived only from concrete numbers; nothing is inferred or
guessed:

* ``absolute_delta`` is the current value minus the baseline **median**
  (expressed in the metric's own units — percentage points for rate metrics,
  raw counts for process pressure).
* ``percentage_delta`` is only computed when the baseline median is non-zero
  (a percentage of a zero baseline is meaningless, so it fails closed to
  ``None``).
* ``z_score`` is only computed when the baseline has dispersion data
  (>= 2 samples); otherwise ``None``.
* ``band`` (NORMAL / ELEVATED / CRITICAL / UNKNOWN) is the severity relative to
  the metric's fixed warn/crit thresholds — it is always computable when a
  current value exists, *independent* of the baseline.

Failure modes fail closed: a missing current value, a missing baseline, or
insufficient baseline samples yield ``UNKNOWN`` bands and ``None`` statistics
rather than a fabricated zero.
"""

from __future__ import annotations

from dataclasses import dataclass

from .baseline import Baseline, BaselineCalculator

#: Minimum baseline samples before dispersion statistics are trustworthy.
_MIN_DEVIATION_SAMPLES = 2

#: Severity bands a deviation can carry.
BAND_NORMAL = "NORMAL"
BAND_ELEVATED = "ELEVATED"
BAND_CRITICAL = "CRITICAL"
BAND_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MetricDeviation:
    """How far a metric's current reading deviates from its observed baseline."""

    metric: str
    label: str
    current: float | None
    baseline_median: float | None
    baseline_p95: float | None
    baseline_mean: float | None
    baseline_stddev: float | None
    baseline_count: int | None
    absolute_delta: float | None
    percentage_delta: float | None
    z_score: float | None
    band: str
    sufficient: bool


def _band_for(
    current: float, *, warn: float, crit: float, higher_is_worse: bool
) -> str:
    """Severity band from fixed thresholds (polarity-aware)."""
    if higher_is_worse:
        if current >= crit:
            return BAND_CRITICAL
        if current >= warn:
            return BAND_ELEVATED
        return BAND_NORMAL
    # Inverted (e.g. battery level): low is bad.
    if current <= crit:
        return BAND_CRITICAL
    if current <= warn:
        return BAND_ELEVATED
    return BAND_NORMAL


def compute_deviation(
    *,
    metric: str,
    label: str,
    current: float | None,
    baseline: Baseline | None,
    warn: float,
    crit: float,
    higher_is_worse: bool = True,
    min_samples: int = _MIN_DEVIATION_SAMPLES,
) -> MetricDeviation:
    """Compute a deterministic :class:`MetricDeviation`.

    Fails closed: when *current* or *baseline* is missing, or the baseline has
    too few samples, statistical fields (delta / percentage / z-score) are
    ``None`` and the band is ``UNKNOWN``. The threshold ``band`` is still
    computed whenever a current value is present, because it needs only the
    fixed thresholds, not the baseline.
    """
    if current is None:
        return MetricDeviation(
            metric=metric, label=label, current=None,
            baseline_median=None, baseline_p95=None, baseline_mean=None,
            baseline_stddev=None, baseline_count=None,
            absolute_delta=None, percentage_delta=None, z_score=None,
            band=BAND_UNKNOWN, sufficient=False,
        )

    band = _band_for(current, warn=warn, crit=crit, higher_is_worse=higher_is_worse)

    if baseline is None or baseline.count < min_samples:
        return MetricDeviation(
            metric=metric, label=label, current=current,
            baseline_median=baseline.median if baseline is not None else None,
            baseline_p95=baseline.p95 if baseline is not None else None,
            baseline_mean=baseline.mean if baseline is not None else None,
            baseline_stddev=baseline.stddev if baseline is not None else None,
            baseline_count=baseline.count if baseline is not None else None,
            absolute_delta=None, percentage_delta=None, z_score=None,
            band=band, sufficient=False,
        )

    absolute_delta = current - baseline.median
    percentage_delta = (
        (current - baseline.median) / baseline.median * 100.0
        if baseline.median != 0.0
        else None
    )
    z_score = BaselineCalculator.zscore(current, baseline)
    return MetricDeviation(
        metric=metric, label=label, current=current,
        baseline_median=baseline.median, baseline_p95=baseline.p95,
        baseline_mean=baseline.mean, baseline_stddev=baseline.stddev,
        baseline_count=baseline.count,
        absolute_delta=absolute_delta, percentage_delta=percentage_delta,
        z_score=z_score, band=band, sufficient=True,
    )


__all__ = [
    "BAND_CRITICAL",
    "BAND_ELEVATED",
    "BAND_NORMAL",
    "BAND_UNKNOWN",
    "MetricDeviation",
    "_MIN_DEVIATION_SAMPLES",
    "compute_deviation",
]
