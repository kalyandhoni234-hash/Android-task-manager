"""Performance view-state model (pure, Qt/ADB-free).

A :class:`PerformanceViewState` is the single, typed object the GUI renders.
It is assembled by :class:`~android_task_manager.performance.orchestrator.PerformanceOrchestrator`
from the existing session, analyzer, tracker and baseline — the UI only reads
it. Keeping the assembly here (pure, deterministic, testable) means the page
stays a renderer and no analysis leaks into ``gui/``.

The state answers the six Phase 3 questions:

* is the device under pressure?      -> ``overall_state``
* which metric?                      -> ``metrics`` conditions
* how strong is the evidence?        -> ``evidence`` + per-metric ``occupancy``
* how does it compare to baseline?   -> ``metrics[*].baseline`` / ``delta``
* which app deserves investigation?  -> ``app_correlations``
* started / active / recovered?      -> ``findings[*].phase`` + ``events``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Tuple

from ..diagnostics.thresholds import (
    CPU_CRITICAL_PERCENT,
    CPU_ELEVATED_PERCENT,
    MEMORY_CRITICAL_PERCENT,
    MEMORY_ELEVATED_PERCENT,
    STORAGE_CRITICAL_PERCENT,
    STORAGE_ELEVATED_PERCENT,
)
from ..thresholds import (
    BATTERY_LEVEL_ELEVATED_PERCENT,
    BATTERY_LEVEL_HIGH_PERCENT,
)
from .models import EvidenceKind

if TYPE_CHECKING:
    from .baseline import Baseline
    from .contributors import ContributorCandidate
    from .deviation import MetricDeviation
    from .episodes import PerformanceEpisode
    from .explanation import Explanation
    from .history_compare import HistoricalComparison
    from .investigation import InvestigationSummary
    from .score import PerformanceScore, ScoreComponent

#: Metric keys surfaced as canonical cards.
METRIC_CPU = "cpu"
METRIC_MEMORY = "memory"
METRIC_STORAGE = "storage"
METRIC_BATTERY = "battery"

#: Overall pressure states the page badge can show.
STATE_NORMAL = "NORMAL"
STATE_CPU_PRESSURE = "CPU_PRESSURE"
STATE_MEMORY_PRESSURE = "MEMORY_PRESSURE"
STATE_STORAGE_PRESSURE = "STORAGE_PRESSURE"
STATE_PROCESS_PRESSURE = "PROCESS_PRESSURE"
STATE_APPLICATION_PRESSURE = "APPLICATION_PRESSURE"
STATE_MULTI_METRIC = "MULTI_METRIC_PRESSURE"
STATE_RECOVERING = "RECOVERING"

#: Window (seconds) after a recovery during which we still show RECOVERING.
RECOVERING_WINDOW_S = 120.0

# Per-metric warn/crit thresholds reused from the diagnostics vocabulary.
_THRESHOLDS: Dict[str, Tuple[float, float]] = {
    METRIC_CPU: (CPU_ELEVATED_PERCENT, CPU_CRITICAL_PERCENT),
    METRIC_MEMORY: (MEMORY_ELEVATED_PERCENT, MEMORY_CRITICAL_PERCENT),
    METRIC_STORAGE: (STORAGE_ELEVATED_PERCENT, STORAGE_CRITICAL_PERCENT),
}

_LABELS: Dict[str, str] = {
    METRIC_CPU: "CPU",
    METRIC_MEMORY: "Memory",
    METRIC_STORAGE: "Storage",
    METRIC_BATTERY: "Battery",
}


@dataclass(frozen=True)
class MetricView:
    """One canonical metric's live card data."""

    key: str
    label: str
    unit: str
    current: float | None
    baseline: Baseline | None
    delta: float | None
    occupancy: float | None
    condition: str
    evidence: str | None


@dataclass(frozen=True)
class FindingView:
    """One active performance finding for the findings list."""

    title: str
    severity: str
    category: str
    evidence: str
    first_seen: float | None
    phase: str


@dataclass(frozen=True)
class EvidenceRow:
    """One evidence line, grouped for the evidence panel."""

    group: str
    metric: str | None
    statement: str
    kind: str


@dataclass(frozen=True)
class AppCorrelation:
    """An already-resolved application shown as correlation (not cause)."""

    package: str
    label: str | None
    cpu_percent: float | None
    memory_percent: float | None
    process_count: int | None
    state: str | None


@dataclass(frozen=True)
class EventRow:
    """One lifecycle transition for the events list."""

    title: str
    severity: str
    phase: str
    monotonic: float | None


@dataclass(frozen=True)
class PerformanceViewState:
    """The complete, render-ready performance surface (pure data)."""

    overall_state: str
    metrics: Dict[str, MetricView]
    findings: Tuple[FindingView, ...]
    evidence: Tuple[EvidenceRow, ...]
    app_correlations: Tuple[AppCorrelation, ...]
    events: Tuple[EventRow, ...]
    history: Dict[str, Tuple[float, ...]]
    #: Phase 4 — explainable intelligence (all pure, derived from the above).
    performance_score: PerformanceScore | None = None
    metric_deviations: Dict[str, MetricDeviation] = field(default_factory=dict)
    trends: Dict[str, str] = field(default_factory=dict)
    contributors: Tuple[ContributorCandidate, ...] = ()
    explanations: Tuple[Explanation, ...] = ()
    investigation_recommendations: Tuple[str, ...] = ()
    #: Phase 5 — historical episodes + investigation (all pure).
    active_episodes: Tuple["PerformanceEpisode", ...] = ()
    recent_episodes: Tuple["PerformanceEpisode", ...] = ()
    episode_count: int = 0
    current_episode: "PerformanceEpisode | None" = None
    investigation_summary: "InvestigationSummary | None" = None
    historical_comparison: "HistoricalComparison | None" = None


def evidence_group(kind: EvidenceKind) -> str:
    """Map an evidence kind to a panel group (observed/baseline/threshold/...)."""
    return {
        EvidenceKind.STATISTIC: "observed",
        EvidenceKind.THRESHOLD_OCCUPANCY: "threshold",
        EvidenceKind.SUSTAINED_THRESHOLD: "threshold",
        EvidenceKind.TREND: "observed",
        EvidenceKind.DELTA: "change",
        EvidenceKind.BASELINE_DEVIATION: "baseline",
        EvidenceKind.PROCESS_PRESSURE: "observed",
        EvidenceKind.APPLICATION_PRESSURE: "correlated",
        EvidenceKind.ANOMALY: "observed",
    }.get(kind, "observed")


def condition_for(
    key: str, current: float | None, warn: float, crit: float
) -> str:
    """Severity-like condition for a metric given its thresholds.

    Battery is inverted (low is bad) and handled by the caller.
    """
    if current is None:
        return "UNKNOWN"
    if current >= crit:
        return "CRITICAL"
    if current >= warn:
        return "ELEVATED"
    return "NORMAL"


__all__ = [
    "AppCorrelation",
    "BATTERY_LEVEL_ELEVATED_PERCENT",
    "BATTERY_LEVEL_HIGH_PERCENT",
    "ContributorCandidate",
    "EvidenceRow",
    "EventRow",
    "Explanation",
    "FindingView",
    "METRIC_BATTERY",
    "METRIC_CPU",
    "METRIC_MEMORY",
    "METRIC_STORAGE",
    "MetricDeviation",
    "MetricView",
    "PerformanceScore",
    "PerformanceViewState",
    "RECOVERING_WINDOW_S",
    "ScoreComponent",
    "STATE_APPLICATION_PRESSURE",
    "STATE_CPU_PRESSURE",
    "STATE_MEMORY_PRESSURE",
    "STATE_MULTI_METRIC",
    "STATE_NORMAL",
    "STATE_PROCESS_PRESSURE",
    "STATE_RECOVERING",
    "STATE_STORAGE_PRESSURE",
    "_LABELS",
    "_THRESHOLDS",
    "condition_for",
    "evidence_group",
]
