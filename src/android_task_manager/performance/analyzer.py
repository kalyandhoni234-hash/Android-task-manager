"""Performance analysis engine (pure, evidence-first, ADB/Qt-free).

The analyzer consumes existing snapshots/samples (fed through
:class:`PerformanceWindow` / :class:`PerformanceSession`) and produces two
kinds of output:

* :class:`PerformanceEvidence` — literal restatements of observed numbers
  (averages, threshold occupancy, sustained spans). These are always emitted
  when data exists, regardless of whether a threshold was crossed.
* :class:`DiagnosticFinding` (the existing, shared diagnostics contract,
  reused verbatim) — emitted **only** when an explicit, evidence-backed rule
  is satisfied (e.g. occupancy at/above a warning threshold). A finding never
  asserts a *cause*; its ``evidence`` field repeats the numbers and its
  ``recommended_action`` points at the existing, verified action vocabulary
  (``force_stop`` etc.) as an *investigation* step — never an automatic
  destructive act.

No value is fabricated. A finding with ``UNKNOWN`` inputs is impossible: every
branch reads concrete sample statistics. The engine creates no timers, opens
no ADB connection and imports no Qt module.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..action.capability import FORCE_STOP
from ..diagnostics.models import (
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticSeverity,
)
from ..diagnostics.thresholds import (
    CPU_CRITICAL_PERCENT,
    CPU_ELEVATED_PERCENT,
    MEMORY_CRITICAL_PERCENT,
    MEMORY_ELEVATED_PERCENT,
    STORAGE_CRITICAL_PERCENT,
    STORAGE_ELEVATED_PERCENT,
)
from .baseline import Baseline
from .evidence import (
    application_pressure_evidence,
    delta_evidence,
    process_pressure_evidence,
    statistic_evidence,
    sustained_threshold_evidence,
    threshold_occupancy_evidence,
)
from .models import PerformanceEvidence
from .window import PerformanceWindow

#: Heuristic process-count pressure thresholds (NOT a device specification).
PROCESS_WARN_COUNT = 280
PROCESS_CRIT_COUNT = 420


@dataclass(frozen=True)
class PerformanceAnalysis:
    """The deterministic result of analyzing one metric/domain."""

    evidence: tuple[PerformanceEvidence, ...]
    findings: tuple[DiagnosticFinding, ...]


class PerformanceAnalyzer:
    """Pure, evidence-first performance analyzer."""

    def __init__(
        self,
        *,
        cpu_warn: float = CPU_ELEVATED_PERCENT,
        cpu_crit: float = CPU_CRITICAL_PERCENT,
        mem_warn: float = MEMORY_ELEVATED_PERCENT,
        mem_crit: float = MEMORY_CRITICAL_PERCENT,
        storage_warn: float = STORAGE_ELEVATED_PERCENT,
        storage_crit: float = STORAGE_CRITICAL_PERCENT,
        proc_warn: float = PROCESS_WARN_COUNT,
        proc_crit: float = PROCESS_CRIT_COUNT,
        sustained_seconds: float = 60.0,
        min_samples: int = 4,
    ) -> None:
        self.cpu_warn = cpu_warn
        self.cpu_crit = cpu_crit
        self.mem_warn = mem_warn
        self.mem_crit = mem_crit
        self.storage_warn = storage_warn
        self.storage_crit = storage_crit
        self.proc_warn = proc_warn
        self.proc_crit = proc_crit
        self.sustained_seconds = sustained_seconds
        self.min_samples = min_samples

    # ------------------------------------------------------------------
    # Canonical live metrics
    # ------------------------------------------------------------------

    def analyze_cpu(
        self, window: PerformanceWindow, baseline: Baseline | None = None,
        timestamp: float | None = None,
    ) -> PerformanceAnalysis:
        return self._analyze_metric(
            window=window, metric="cpu", category=DiagnosticCategory.CPU,
            warn=self.cpu_warn, crit=self.cpu_crit, baseline=baseline,
            timestamp=timestamp if timestamp is not None else 0.0,
        )

    def analyze_memory(
        self, window: PerformanceWindow, baseline: Baseline | None = None,
        timestamp: float | None = None,
    ) -> PerformanceAnalysis:
        return self._analyze_metric(
            window=window, metric="memory", category=DiagnosticCategory.MEMORY,
            warn=self.mem_warn, crit=self.mem_crit, baseline=baseline,
            timestamp=timestamp if timestamp is not None else 0.0,
        )

    def analyze_storage(
        self, window: PerformanceWindow, baseline: Baseline | None = None,
        timestamp: float | None = None,
    ) -> PerformanceAnalysis:
        return self._analyze_metric(
            window=window, metric="storage", category=DiagnosticCategory.STORAGE,
            warn=self.storage_warn, crit=self.storage_crit, baseline=baseline,
            timestamp=timestamp if timestamp is not None else 0.0,
        )

    def _analyze_metric(
        self, *, window: PerformanceWindow, metric: str,
        category: DiagnosticCategory, warn: float, crit: float,
        baseline: Baseline | None, timestamp: float,
    ) -> PerformanceAnalysis:
        if window.is_empty or metric not in window.metrics():
            return PerformanceAnalysis(evidence=(), findings=())

        evidence: list[PerformanceEvidence] = [
            statistic_evidence(f"EVID-{metric}-stat", timestamp, metric, window),
            threshold_occupancy_evidence(
                f"EVID-{metric}-occ-warn", timestamp, metric, window, warn
            ),
            threshold_occupancy_evidence(
                f"EVID-{metric}-occ-crit", timestamp, metric, window, crit
            ),
        ]
        sustained = sustained_threshold_evidence(
            f"EVID-{metric}-sustained", timestamp, metric, window, warn,
            self.sustained_seconds,
        )
        if sustained is not None:
            evidence.append(sustained)
        if baseline is not None:
            evidence.append(
                delta_evidence(f"EVID-{metric}-delta", timestamp, metric, window, baseline)
            )

        occupancy_crit = window.threshold_occupancy(metric, crit)
        occupancy_warn = window.threshold_occupancy(metric, warn)
        # A finding needs enough samples to be meaningful: a single high tick
        # is not a sustained condition. Evidence is still produced.
        if len(window) < self.min_samples:
            return PerformanceAnalysis(evidence=tuple(evidence), findings=())
        findings: list[DiagnosticFinding] = []
        if occupancy_crit > 0.0:
            findings.append(self._metric_finding(
                metric=metric, category=category,
                severity=DiagnosticSeverity.CRITICAL, warn=warn, crit=crit,
                occupancy=occupancy_crit, window=window, evidence=evidence,
            ))
        elif occupancy_warn > 0.0:
            findings.append(self._metric_finding(
                metric=metric, category=category,
                severity=DiagnosticSeverity.WARNING, warn=warn, crit=crit,
                occupancy=occupancy_warn, window=window, evidence=evidence,
            ))
        return PerformanceAnalysis(evidence=tuple(evidence), findings=tuple(findings))

    def _metric_finding(
        self, *, metric: str, category: DiagnosticCategory,
        severity: DiagnosticSeverity, warn: float, crit: float,
        occupancy: float, window: PerformanceWindow,
        evidence: Sequence[PerformanceEvidence],
    ) -> DiagnosticFinding:
        avg = window.average(metric)
        count = len(window)
        level = "critical" if severity is DiagnosticSeverity.CRITICAL else "elevated"
        what = f"{metric} utilization is {level}."
        why = (
            f"{occupancy * 100:.1f}% of {count} samples were at or above the "
            f"{'critical' if severity is DiagnosticSeverity.CRITICAL else 'warning'} "
            f"threshold ({crit if severity is DiagnosticSeverity.CRITICAL else warn:.0f}%)."
        )
        evidence_text = (
            f"{metric} averaged {avg:.1f}% over {count} samples; "
            f"{occupancy * 100:.1f}% of samples at/above threshold."
        )
        action = (
            f"Investigate top {metric} consumers in the process / background-apps "
            f"panel; high-cost user apps may be force-stopped via the action panel "
            f"({FORCE_STOP}). No automatic termination is performed."
        )
        return DiagnosticFinding(
            severity=severity,
            category=category,
            title=f"{metric.upper()} {level}",
            what=what,
            why=why,
            evidence=evidence_text,
            recommended_action=action,
        )

    # ------------------------------------------------------------------
    # Process pressure
    # ------------------------------------------------------------------

    def analyze_process_pressure(
        self, window: PerformanceWindow, baseline: Baseline | None = None,
        timestamp: float | None = None,
    ) -> PerformanceAnalysis:
        metric = "process_count"
        if window.is_empty or metric not in window.metrics():
            return PerformanceAnalysis(evidence=(), findings=())
        ts = timestamp if timestamp is not None else 0.0
        evidence = [process_pressure_evidence(
            "EVID-proc-press", ts, window, self.proc_warn, self.proc_crit
        )]
        if baseline is not None:
            evidence.append(delta_evidence(
                "EVID-proc-delta", ts, metric, window, baseline
            ))
        latest = window.latest(metric)
        if len(window) < self.min_samples:
            return PerformanceAnalysis(evidence=tuple(evidence), findings=())
        findings: list[DiagnosticFinding] = []
        if latest is not None and latest >= self.proc_crit:
            findings.append(self._pressure_finding(
                severity=DiagnosticSeverity.CRITICAL, latest=latest, evidence=evidence))
        elif latest is not None and latest >= self.proc_warn:
            findings.append(self._pressure_finding(
                severity=DiagnosticSeverity.WARNING, latest=latest, evidence=evidence))
        return PerformanceAnalysis(evidence=tuple(evidence), findings=tuple(findings))

    def _pressure_finding(
        self, *, severity: DiagnosticSeverity, latest: float,
        evidence: Sequence[PerformanceEvidence],
    ) -> DiagnosticFinding:
        level = "critical" if severity is DiagnosticSeverity.CRITICAL else "elevated"
        return DiagnosticFinding(
            severity=severity,
            category=DiagnosticCategory.PROCESS,
            title=f"Process pressure ({level})",
            what=f"Running process count is {level} ({latest:.0f}).",
            why=(
                f"Latest running process count {latest:.0f} is at/above the "
                f"{level} threshold "
                f"({self.proc_crit if severity is DiagnosticSeverity.CRITICAL else self.proc_warn:.0f})."
            ),
            evidence=f"running process count latest {latest:.0f}",
            recommended_action=(
                "Inspect the process list for runaway or duplicated processes; "
                "user apps may be force-stopped via the action panel "
                f"({FORCE_STOP}). No automatic termination is performed."
            ),
        )

    # ------------------------------------------------------------------
    # Application pressure (identity already resolved by the caller)
    # ------------------------------------------------------------------

    def analyze_application_pressure(
        self,
        app_loads: Sequence[tuple[str, str | None, float | None, float | None]],
        top_n: int = 5,
        timestamp: float | None = None,
    ) -> PerformanceAnalysis:
        """Analyze per-application load from already-resolved identity.

        *app_loads* is ``(package, label, cpu_percent, memory_percent)`` —
        the caller is responsible for process→package→label resolution (the
        v0.8.1 Background User Apps identity pipeline). The analyzer never
        resolves identity itself, so no duplicate ADB/inventory logic exists.
        """
        ts = timestamp if timestamp is not None else 0.0
        if not app_loads:
            return PerformanceAnalysis(evidence=(), findings=())
        ranked = sorted(
            app_loads,
            key=lambda t: (t[2] or 0.0) + (t[3] or 0.0),
            reverse=True,
        )[:top_n]
        evidence: list[PerformanceEvidence] = []
        findings: list[DiagnosticFinding] = []
        for i, (package, label, cpu, mem) in enumerate(ranked):
            evidence.append(application_pressure_evidence(
                f"EVID-app-{i}", ts, package, label, cpu, mem
            ))
        top = ranked[0]
        findings.append(DiagnosticFinding(
            severity=DiagnosticSeverity.INFO,
            category=DiagnosticCategory.PROCESS,
            title="Top application load",
            what=f"{top[1] or top[0]} is the heaviest observed application.",
            why=(
                f"Ranked first by summed cpu/memory among "
                f"{len(app_loads)} resolved applications."
            ),
            evidence=f"top: {top[1] or top[0]} (cpu={top[2]}, mem={top[3]})",
            recommended_action=(
                f"If unwanted, force-stop via the action panel ({FORCE_STOP}); "
                "no automatic termination is performed."
            ),
        ))
        return PerformanceAnalysis(evidence=tuple(evidence), findings=tuple(findings))


__all__ = [
    "PROCESS_CRIT_COUNT",
    "PROCESS_WARN_COUNT",
    "PerformanceAnalysis",
    "PerformanceAnalyzer",
]
