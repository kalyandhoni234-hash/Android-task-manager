"""Deterministic evidence builders.

Every helper returns a :class:`PerformanceEvidence` whose ``statement`` is a
literal restatement of the numbers passed in. No helper invents a cause; the
wording is always "what was observed", never "why it happened".

These builders are the single place where evidence sentences are formatted, so
the analysis engine stays free of string-concatenation and the wording stays
consistent and auditable.
"""

from __future__ import annotations

from .baseline import Baseline
from .models import EvidenceKind, PerformanceEvidence
from .window import PerformanceWindow


def _fmt(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def statistic_evidence(
    evidence_id: str,
    timestamp: float,
    metric: str,
    window: PerformanceWindow,
    digits: int = 1,
) -> PerformanceEvidence:
    avg = window.average(metric)
    mn = window.minimum(metric)
    mx = window.maximum(metric)
    trend = window.trend(metric).value
    statement = (
        f"{metric} averaged {_fmt(avg, digits)}% "
        f"(min {_fmt(mn, digits)}%, max {_fmt(mx, digits)}%, "
        f"trend {trend}) over {len(window)} samples"
    )
    return PerformanceEvidence(
        evidence_id=evidence_id,
        timestamp=timestamp,
        kind=EvidenceKind.STATISTIC,
        statement=statement,
        metric=metric,
        value=avg,
        sample_count=len(window),
    )


def threshold_occupancy_evidence(
    evidence_id: str,
    timestamp: float,
    metric: str,
    window: PerformanceWindow,
    threshold: float,
    digits: int = 1,
) -> PerformanceEvidence:
    occupancy = window.threshold_occupancy(metric, threshold)
    statement = (
        f"{metric} was at or above {_fmt(threshold, digits)}% "
        f"for {occupancy * 100:.1f}% of {len(window)} samples"
    )
    return PerformanceEvidence(
        evidence_id=evidence_id,
        timestamp=timestamp,
        kind=EvidenceKind.THRESHOLD_OCCUPANCY,
        statement=statement,
        metric=metric,
        threshold=threshold,
        value=occupancy,
        sample_count=len(window),
    )


def sustained_threshold_evidence(
    evidence_id: str,
    timestamp: float,
    metric: str,
    window: PerformanceWindow,
    threshold: float,
    duration: float,
    digits: int = 1,
) -> PerformanceEvidence | None:
    since = window.sustained_threshold(metric, threshold, duration)
    if since is None:
        return None
    statement = (
        f"{metric} has stayed at or above {_fmt(threshold, digits)}% "
        f"continuously for at least {duration:.1f}s (since sample at "
        f"{since:.1f})"
    )
    return PerformanceEvidence(
        evidence_id=evidence_id,
        timestamp=timestamp,
        kind=EvidenceKind.SUSTAINED_THRESHOLD,
        statement=statement,
        metric=metric,
        threshold=threshold,
        duration=duration,
        value=window.latest(metric),
    )


def trend_evidence(
    evidence_id: str,
    timestamp: float,
    metric: str,
    window: PerformanceWindow,
) -> PerformanceEvidence:
    trend = window.trend(metric)
    statement = f"{metric} trend is {trend.value} over {len(window)} samples"
    return PerformanceEvidence(
        evidence_id=evidence_id,
        timestamp=timestamp,
        kind=EvidenceKind.TREND,
        statement=statement,
        metric=metric,
        sample_count=len(window),
    )


def delta_evidence(
    evidence_id: str,
    timestamp: float,
    metric: str,
    window: PerformanceWindow,
    baseline: Baseline,
    digits: int = 1,
) -> PerformanceEvidence:
    delta = window.change_from_baseline(metric, baseline.mean)
    statement = (
        f"{metric} average {_fmt(window.average(metric), digits)}% is "
        f"{_fmt(delta, digits)} pp from baseline mean "
        f"{_fmt(baseline.mean, digits)}%"
    )
    return PerformanceEvidence(
        evidence_id=evidence_id,
        timestamp=timestamp,
        kind=EvidenceKind.DELTA,
        statement=statement,
        metric=metric,
        value=delta,
        sample_count=len(window),
    )


def process_pressure_evidence(
    evidence_id: str,
    timestamp: float,
    window: PerformanceWindow,
    warn: float,
    crit: float,
) -> PerformanceEvidence:
    latest = window.latest("process_count")
    avg = window.average("process_count")
    statement = (
        f"running process count averaged {_fmt(avg, 0)} "
        f"(latest {_fmt(latest, 0)}; warn >= {warn:.0f}, crit >= {crit:.0f})"
    )
    return PerformanceEvidence(
        evidence_id=evidence_id,
        timestamp=timestamp,
        kind=EvidenceKind.PROCESS_PRESSURE,
        statement=statement,
        metric="process_count",
        value=latest,
        threshold=crit,
        sample_count=len(window),
    )


def application_pressure_evidence(
    evidence_id: str,
    timestamp: float,
    package: str,
    label: str | None,
    cpu_percent: float | None,
    memory_percent: float | None,
) -> PerformanceEvidence:
    name = label or package
    parts = []
    if cpu_percent is not None:
        parts.append(f"cpu {cpu_percent:.1f}%")
    if memory_percent is not None:
        parts.append(f"mem {memory_percent:.1f}%")
    what = ", ".join(parts) if parts else "no metric reported"
    statement = f"{name} ({package}) consuming {what}"
    return PerformanceEvidence(
        evidence_id=evidence_id,
        timestamp=timestamp,
        kind=EvidenceKind.APPLICATION_PRESSURE,
        statement=statement,
        metric="application",
        value=cpu_percent if cpu_percent is not None else memory_percent,
        entity=package,
    )


__all__ = [
    "application_pressure_evidence",
    "delta_evidence",
    "process_pressure_evidence",
    "statistic_evidence",
    "sustained_threshold_evidence",
    "threshold_occupancy_evidence",
    "trend_evidence",
]
