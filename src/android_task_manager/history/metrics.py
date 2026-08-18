"""Bounded historical metric windows with deterministic statistics.

Pure, GUI-independent, zero-ADB: a metric history is a fixed-size window of
(value, timestamp) samples with explicit semantics:

* ``None`` values are never recorded (unavailable stays unavailable);
* consecutive duplicate values are dropped (a polling cycle that observed
  no change is not new history);
* the window is bounded (``max_samples``) — memory growth is capped;
* statistics (min/max/avg/latest/trend) and peak periods are derived from
  the window on demand and are deterministic.

Trend direction is explainable: the window is split in halves and the
recent-half mean is compared against the older-half mean with a relative
epsilon. With too few samples the trend is ``INSUFFICIENT`` — never guessed.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Iterator

#: Minimum samples before a trend direction can be claimed.
MIN_TREND_SAMPLES = 4

#: Relative change (|recent − older| / max(|older|, 1)) below which the
#: trend is FLAT. 1% of the older mean.
TREND_EPSILON_RELATIVE = 0.01


class TrendDirection(Enum):
    """Deterministic trend of a metric window."""

    RISING = "rising"
    FALLING = "falling"
    FLAT = "flat"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class Sample:
    """One recorded metric sample."""

    value: float
    timestamp: float


@dataclass(frozen=True)
class MetricStats:
    """Statistics over the current history window.

    ``latest`` is the most recent recorded sample (never fabricated from
    the average). All statistics are ``None`` when the window is empty.
    """

    count: int
    minimum: float | None
    maximum: float | None
    average: float | None
    latest: float | None
    trend: TrendDirection
    first_timestamp: float | None
    last_timestamp: float | None


@dataclass(frozen=True)
class PeakPeriod:
    """A run of consecutive samples at or above a threshold."""

    start_timestamp: float
    end_timestamp: float
    peak_value: float
    sample_count: int


class MetricHistory:
    """A bounded, deduplicating window of metric samples."""

    def __init__(self, max_samples: int = 180, dedupe: bool = True) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be >= 1")
        self._max_samples = max_samples
        self._dedupe = dedupe
        self._samples: Deque[Sample] = deque(maxlen=max_samples)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def add_sample(self, value: float | None, timestamp: float | None = None) -> None:
        """Record *value* unless it is unavailable or a duplicate of the
        previous recorded value."""
        if value is None:
            return
        if self._dedupe and self._samples and self._samples[-1].value == value:
            return
        if timestamp is None:
            timestamp = time.monotonic()
        self._samples.append(Sample(float(value), float(timestamp)))

    def clear(self) -> None:
        """Drop every sample (device disconnected / new session)."""
        self._samples.clear()

    def resize(self, max_samples: int) -> None:
        """Change the window bound; older samples beyond it are dropped."""
        if max_samples < 1:
            raise ValueError("max_samples must be >= 1")
        self._max_samples = max_samples
        kept = list(self._samples)[-max_samples:]
        self._samples = deque(kept, maxlen=max_samples)

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

    def __iter__(self) -> Iterator[Sample]:
        return iter(tuple(self._samples))

    def latest(self) -> float | None:
        """Most recently recorded value (or None when empty)."""
        return self._samples[-1].value if self._samples else None

    def stats(self) -> MetricStats:
        """Deterministic statistics over the current window."""
        if not self._samples:
            return MetricStats(
                count=0,
                minimum=None,
                maximum=None,
                average=None,
                latest=None,
                trend=TrendDirection.INSUFFICIENT,
                first_timestamp=None,
                last_timestamp=None,
            )
        values = [sample.value for sample in self._samples]
        timestamps = [sample.timestamp for sample in self._samples]
        return MetricStats(
            count=len(values),
            minimum=min(values),
            maximum=max(values),
            average=sum(values) / len(values),
            latest=values[-1],
            trend=self._trend(),
            first_timestamp=timestamps[0],
            last_timestamp=timestamps[-1],
        )

    def peak_periods(
        self, threshold: float, min_samples: int = 2
    ) -> tuple[PeakPeriod, ...]:
        """Runs of consecutive samples at or above *threshold*.

        Runs shorter than *min_samples* are ignored (a single blip is not a
        peak period). Returns an empty tuple when there is no qualifying
        run.
        """
        if min_samples < 1:
            raise ValueError("min_samples must be >= 1")
        runs: list[list[Sample]] = []
        current: list[Sample] = []
        for sample in self._samples:
            if sample.value >= threshold:
                current.append(sample)
            elif current:
                runs.append(current)
                current = []
        if current:
            runs.append(current)
        periods = []
        for run in runs:
            if len(run) < min_samples:
                continue
            periods.append(
                PeakPeriod(
                    start_timestamp=run[0].timestamp,
                    end_timestamp=run[-1].timestamp,
                    peak_value=max(sample.value for sample in run),
                    sample_count=len(run),
                )
            )
        return tuple(periods)

    def sustained_since(self, threshold: float, duration: float) -> float | None:
        """The earliest timestamp from which *value >= threshold* has held
        continuously for at least *duration* (in the same time units as the
        sample timestamps), or None.

        Supports "IF metric >= threshold FOR duration" rules: the walk goes
        backwards from the latest sample while the condition holds; when the
        accumulated span reaches *duration*, the timestamp where that run
        started is returned. A run is only trusted while it stays above the
        threshold — a single dip breaks it.
        """
        if len(self._samples) < 2:
            return None
        run_end = self._samples[-1].timestamp
        run_start = run_end
        for sample in reversed(tuple(self._samples)):
            if sample.value < threshold:
                return None
            run_start = sample.timestamp
            if run_end - run_start >= duration:
                return run_start
        return None

    def _trend(self) -> TrendDirection:
        """Compare the recent half's mean against the older half's mean."""
        samples = list(self._samples)
        count = len(samples)
        if count < MIN_TREND_SAMPLES:
            return TrendDirection.INSUFFICIENT
        split = count // 2
        older = [sample.value for sample in samples[:split]]
        recent = [sample.value for sample in samples[split:]]
        older_mean = sum(older) / len(older)
        recent_mean = sum(recent) / len(recent)
        if older_mean == 0.0:
            if recent_mean == 0.0:
                return TrendDirection.FLAT
            return TrendDirection.RISING
        relative = (recent_mean - older_mean) / abs(older_mean)
        if relative > TREND_EPSILON_RELATIVE:
            return TrendDirection.RISING
        if relative < -TREND_EPSILON_RELATIVE:
            return TrendDirection.FALLING
        return TrendDirection.FLAT


__all__ = [
    "MetricHistory",
    "MetricStats",
    "PeakPeriod",
    "Sample",
    "TrendDirection",
]
