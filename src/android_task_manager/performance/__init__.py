"""Advanced performance & root-cause intelligence (v0.9.0 foundation).

Qt-independent, ADB-independent, deterministic. This package establishes the
analysis-scoped domain for the Advanced Performance & Root-Cause Intelligence
feature. It deliberately reuses existing primitives instead of reimplementing
them:

* window/baseline statistics build on
  :mod:`android_task_manager.history.metrics` (``MetricHistory``,
  ``MetricStats``, ``TrendDirection``);
* session reset semantics reuse
  :mod:`android_task_manager.history.session` (``SessionHistory``);
* findings reuse :mod:`android_task_manager.diagnostics.models`
  (``DiagnosticFinding`` / ``DiagnosticSeverity`` / ``DiagnosticCategory``);
* thresholds reuse :mod:`android_task_manager.diagnostics.thresholds`;
* events adapt to :mod:`android_task_manager.timeline.models`
  (``TimelineEvent``) via :func:`performance.events.to_timeline_event`;
* application correlation consumes identity already resolved by the v0.8.1
  Background User Apps pipeline — never re-resolved here.

Nothing in this package creates a timer, opens an ADB connection, imports Qt,
or fabricates a metric or a cause.
"""

from __future__ import annotations

from .analyzer import (
    PROCESS_CRIT_COUNT,
    PROCESS_WARN_COUNT,
    PerformanceAnalysis,
    PerformanceAnalyzer,
)
from .baseline import Baseline, BaselineCalculator
from .contributors import ContributorCandidate, rank_contributors
from .deviation import MetricDeviation, compute_deviation
from .episode_tracker import (
    EPISODE_RETENTION,
    EVIDENCE_RETENTION,
    EpisodeLifecycle,
    EpisodeRecord,
    EpisodeTracker,
    EpisodeUpdate,
)
from .episodes import (
    ContributorCorrelation,
    PerformanceEpisode,
    build_episode,
    build_grouped_episode,
    correlate_contributors,
)
from .events import (
    PerformanceEvent,
    PerformanceEventType,
    to_timeline_event,
)
from .explanation import Explanation, build_explanation, build_recommendations
from .history_compare import (
    INSUFFICIENT,
    HistoricalComparison,
    build_historical_comparison,
    find_comparable,
)
from .investigation import InvestigationSummary, build_investigation_summary
from .models import (
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticSeverity,
    EvidenceKind,
    PerformanceEvidence,
    PerformanceMetric,
    PerformanceSample,
)
from .orchestrator import OrchestratorResult, PerformanceOrchestrator
from .score import PerformanceScore, ScoreComponent, compute_score
from .session import PerformanceSession
from .tracker import ActiveCondition, ConditionPhase, ConditionTracker, TrackerStep
from .translation import (
    app_loads_from_background,
    battery_level_percent,
    cpu_used_percent,
    memory_used_percent,
    network_throughput,
    process_count,
    storage_used_percent,
)
from .trend import classify_trend
from .view import PerformanceViewState
from .window import PerformanceWindow

__all__ = [
    "ActiveCondition",
    "Baseline",
    "BaselineCalculator",
    "ConditionPhase",
    "ConditionTracker",
    "ContributorCandidate",
    "ContributorCorrelation",
    "EVIDENCE_RETENTION",
    "EPISODE_RETENTION",
    "EpisodeLifecycle",
    "EpisodeRecord",
    "EpisodeTracker",
    "EpisodeUpdate",
    "Explanation",
    "HistoricalComparison",
    "INSUFFICIENT",
    "InvestigationSummary",
    "MetricDeviation",
    "OrchestratorResult",
    "PerformanceAnalysis",
    "PerformanceAnalyzer",
    "PerformanceEvent",
    "PerformanceEventType",
    "PerformanceEvidence",
    "PerformanceMetric",
    "PerformanceEpisode",
    "PerformanceOrchestrator",
    "PerformanceScore",
    "PerformanceSample",
    "PerformanceSession",
    "PerformanceViewState",
    "PerformanceWindow",
    "ScoreComponent",
    "TrackerStep",
    "build_explanation",
    "build_grouped_episode",
    "build_recommendations",
    "classify_trend",
    "compute_deviation",
    "compute_score",
    "build_episode",
    "PerformanceEpisode",
    "find_comparable",
    "build_historical_comparison",
    "build_investigation_summary",
    "correlate_contributors",
    "DiagnosticCategory",
    "DiagnosticFinding",
    "DiagnosticSeverity",
    "EvidenceKind",
    "PROCESS_CRIT_COUNT",
    "PROCESS_WARN_COUNT",
    "app_loads_from_background",
    "battery_level_percent",
    "cpu_used_percent",
    "memory_used_percent",
    "network_throughput",
    "process_count",
    "rank_contributors",
    "storage_used_percent",
    "to_timeline_event",
]
