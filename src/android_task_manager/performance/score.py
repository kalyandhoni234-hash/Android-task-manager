"""Deterministic, explainable performance score (pure, Qt/ADB-free).

The score is an *observed* health summary: a single 0–100 number derived only
from the same metrics the dashboard already shows. It is explicitly NOT a claim
about OS-level truth — it is a transparent summary of how far the observed
telemetry sits from healthy thresholds.

Calculation (documented, deterministic)
---------------------------------------
Start from 100. For each supported metric a maximum penalty is defined
(CPU 25, Memory 25, Storage 20, Process 15, Battery 15 — summing to 100 so a
fully-pressured device reaches 0). Each metric's contribution is:

    contribution = -round(max_penalty * weight(band))

where ``weight`` is ``0.0`` for NORMAL/UNKNOWN, ``0.5`` for ELEVATED and
``1.0`` for CRITICAL. The final score is ``clamp(100 + sum(contributions), 0,
100)``.

Every component carries its own contribution and the band that produced it, so
the UI can explain exactly why the score moved. No machine-learning, no opaque
blending, no fabricated sub-scores.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .deviation import BAND_CRITICAL, BAND_ELEVATED, BAND_NORMAL, BAND_UNKNOWN, MetricDeviation

#: Maximum penalty each metric can subtract from the 100-point score.
DEFAULT_MAX_PENALTIES: dict[str, int] = {
    "cpu": 25,
    "memory": 25,
    "storage": 20,
    "process": 15,
    "battery": 15,
}

#: Band -> contribution weight (fraction of the metric's max penalty).
_BAND_WEIGHT = {
    BAND_NORMAL: 0.0,
    BAND_UNKNOWN: 0.0,
    BAND_ELEVATED: 0.5,
    BAND_CRITICAL: 1.0,
}


@dataclass(frozen=True)
class ScoreComponent:
    """One metric's contribution to the overall score (explainable)."""

    metric: str
    label: str
    current: float | None
    band: str
    max_penalty: int
    contribution: int
    detail: str


@dataclass(frozen=True)
class PerformanceScore:
    """The explainable observed-performance score and its components."""

    score: int
    components: tuple[ScoreComponent, ...]
    sufficient: bool


def compute_score(
    deviations: Mapping[str, MetricDeviation],
    max_penalties: Mapping[str, int] | None = None,
) -> PerformanceScore:
    """Compute the deterministic performance score from per-metric deviations.

    *deviations* maps a metric key (``cpu``/``memory``/``storage``/``process``/
    ``battery``) to its :class:`MetricDeviation`. Metrics absent or with an
    ``UNKNOWN`` band contribute nothing; the score only drops for metrics whose
    current reading crosses a threshold band.
    """
    penalties = dict(DEFAULT_MAX_PENALTIES)
    if max_penalties:
        penalties.update(max_penalties)

    components: list[ScoreComponent] = []
    total = 0
    sufficient = False
    for key, dev in deviations.items():
        max_penalty = penalties.get(key, 0)
        if max_penalty == 0:
            continue
        weight = _BAND_WEIGHT.get(dev.band, 0.0)
        contribution = -round(max_penalty * weight)
        total += contribution
        if dev.sufficient:
            sufficient = True
        components.append(ScoreComponent(
            metric=key,
            label=dev.label,
            current=dev.current,
            band=dev.band,
            max_penalty=max_penalty,
            contribution=contribution,
            detail=f"{dev.label} {dev.band.lower()}",
        ))

    score = max(0, min(100, 100 + total))
    return PerformanceScore(
        score=score,
        components=tuple(components),
        sufficient=sufficient,
    )


__all__ = [
    "DEFAULT_MAX_PENALTIES",
    "PerformanceScore",
    "ScoreComponent",
    "compute_score",
]
