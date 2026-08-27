"""Deterministic trend classification (pure, Qt/ADB-free).

Classifies the recent direction of a metric's window into one of:

* ``STABLE``
* ``IMPROVING``
* ``DEGRADING``
* ``RECOVERING``
* ``INSUFFICIENT_DATA``

The classifier uses only the values already recorded in the existing
:class:`~android_task_manager.performance.window.PerformanceWindow` — it does
**not** create a new sampling mechanism.

Method (documented thresholds)
--------------------------------
1. Fewer than ``min_samples`` (default 4) values -> ``INSUFFICIENT_DATA``.
2. Split the series into a first half and a second half; compare their means.
3. If ``|second_half_mean - first_half_mean| <= stable_threshold`` (default
   2.0 in the metric's own units) -> ``STABLE``.
4. Otherwise the sign of the change gives the direction. For most metrics a
   *rising* value is worse (``higher_is_worse=True``): rising => ``DEGRADING``,
   falling => ``IMPROVING``. For battery level the polarity is inverted
   (``higher_is_worse=False``).
5. ``RECOVERING`` is ``IMPROVING`` *while still above the pressure reference*
   (``recovering_reference``): the metric is coming down from a high
   pressure value. Without that context an improving series is simply
   ``IMPROVING``.

All comparisons are deterministic and unit-agnostic (they operate on the raw
recorded floats).
"""

from __future__ import annotations

from collections.abc import Sequence

TREND_STABLE = "STABLE"
TREND_IMPROVING = "IMPROVING"
TREND_DEGRADING = "DEGRADING"
TREND_RECOVERING = "RECOVERING"
TREND_INSUFFICIENT = "INSUFFICIENT_DATA"

#: Default minimum samples before a direction can be trusted.
_DEFAULT_MIN_SAMPLES = 4
#: Default maximum absolute half-mean difference still considered STABLE.
_DEFAULT_STABLE_THRESHOLD = 2.0


def classify_trend(
    values: Sequence[float],
    higher_is_worse: bool = True,
    stable_threshold: float = _DEFAULT_STABLE_THRESHOLD,
    min_samples: int = _DEFAULT_MIN_SAMPLES,
    recovering_reference: float | None = None,
) -> str:
    """Classify the trend of *values* (oldest first) into a TrendState string."""
    if len(values) < min_samples:
        return TREND_INSUFFICIENT

    half = len(values) // 2
    if half == 0:
        return TREND_INSUFFICIENT
    first_mean = sum(values[:half]) / half
    second_mean = sum(values[half:]) / (len(values) - half)
    delta = second_mean - first_mean

    if abs(delta) <= stable_threshold:
        return TREND_STABLE

    rising = delta > 0
    worsening = rising if higher_is_worse else not rising
    base = TREND_DEGRADING if worsening else TREND_IMPROVING

    if base == TREND_IMPROVING and recovering_reference is not None:
        if values[-1] >= recovering_reference:
            return TREND_RECOVERING
    return base


__all__ = [
    "TREND_DEGRADING",
    "TREND_IMPROVING",
    "TREND_INSUFFICIENT",
    "TREND_RECOVERING",
    "TREND_STABLE",
    "classify_trend",
]
