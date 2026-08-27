"""Performance orchestration over the existing monitor pipeline (pure).

A :class:`PerformanceOrchestrator` is the Qt-independent brain that the GUI
adapter drives. On every monitor update it:

1. translates the existing snapshots into plain metrics (reusing the same
   derivation rules as the dashboard/health engine);
2. records them into a :class:`PerformanceSession` (no new polling — the
   monitor's single tick is the only source);
3. runs the pure :class:`PerformanceAnalyzer`;
4. collapses the resulting findings into a deduplicated lifecycle via the
   :class:`ConditionTracker`, so a sustained breach yields exactly one
   finding plus STARTED / (throttled) ACTIVE / RECOVERED events.

It owns no timer, no ADB connection and no Qt object. Application identity is
consumed already-resolved from the v0.8.1 Background User Apps snapshot — it
is never re-resolved here.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from ..background.models import BackgroundAppsSnapshot
from ..battery.models import BatterySnapshot
from ..cpu.models import CPUSnapshot
from ..diagnostics.models import DiagnosticCategory, DiagnosticFinding
from ..memory.models import MemorySnapshot
from ..network.models import NetworkSnapshot
from ..process.models import ProcessSnapshot
from ..storage.models import StorageSnapshot
from ..thresholds import (
    BATTERY_LEVEL_ELEVATED_PERCENT,
    BATTERY_LEVEL_HIGH_PERCENT,
)
from .analyzer import PerformanceAnalyzer
from .baseline import BaselineCalculator
from .contributors import ContributorCandidate, rank_contributors
from .deviation import MetricDeviation, compute_deviation
from .episode_tracker import EpisodeTracker
from .episodes import (
    EpisodeLifecycle,
    PerformanceEpisode,
    build_grouped_episode,
    format_duration,
)
from .events import PerformanceEvent, PerformanceEventType
from .evidence import PerformanceEvidence
from .explanation import build_explanation, build_recommendations
from .history_compare import build_historical_comparison, find_comparable
from .investigation import build_investigation_summary
from .models import EvidenceKind, PerformanceMetric
from .score import compute_score
from .session import PerformanceSession
from .tracker import ActiveCondition, ConditionTracker, TrackerStep
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
from .view import METRIC_BATTERY, MetricView, PerformanceViewState

#: Map a condition metric key to its normalized performance event type.
_METRIC_EVENT_TYPE = {
    DiagnosticCategory.CPU.value: PerformanceEventType.CPU_PRESSURE,
    DiagnosticCategory.MEMORY.value: PerformanceEventType.MEMORY_PRESSURE,
    DiagnosticCategory.STORAGE.value: PerformanceEventType.STORAGE_PRESSURE,
    DiagnosticCategory.PROCESS.value: PerformanceEventType.PROCESS_PRESSURE,
    "application": PerformanceEventType.APPLICATION_PRESSURE,
}

#: Condition metric -> session window key (reuse existing windows).
_WINDOW_KEY = {
    "cpu": "cpu",
    "memory": "memory",
    "storage": "storage",
    "battery": "battery",
    "process": "process_count",
    "application": "process_count",
}

#: Condition metric -> contributor-pressure vocabulary (contributors.py).
_PRESSURE_NAME = {
    "cpu": "cpu",
    "memory": "memory",
    "storage": "storage",
    "process": "process",
    "application": "process",
}

#: Conditions that can form or hold an episode. Application-pressure findings
#: are unconditional while background apps are monitored (informational
#: "top application load"), so they are correlation CONTEXT: they neither open
#: nor hold an episode — otherwise no episode could ever recover.
_EPISODE_METRICS = frozenset({"cpu", "memory", "storage", "process"})


@dataclass(frozen=True)
class OrchestratorResult:
    """What one ``ingest`` produced."""

    evidence: tuple[PerformanceEvidence, ...] = ()
    #: Only findings for *newly started* conditions (deduplicated).
    findings: tuple[DiagnosticFinding, ...] = ()
    events: tuple[PerformanceEvent, ...] = ()


class PerformanceOrchestrator:
    """Ties session + analyzer + tracker together; pure and deterministic."""

    def __init__(
        self,
        *,
        session: PerformanceSession | None = None,
        analyzer: PerformanceAnalyzer | None = None,
        tracker: ConditionTracker | None = None,
        episodes: EpisodeTracker | None = None,
    ) -> None:
        self.session = session or PerformanceSession()
        self.analyzer = analyzer or PerformanceAnalyzer()
        self.tracker = tracker or ConditionTracker()
        #: Phase 5: groups condition lifecycles into bounded performance
        #: episodes (deterministic ids, severity/metric aggregation, score
        #: trajectory, evidence retention). Pure domain, no polling.
        self.episodes = episodes or EpisodeTracker()
        self._background_apps: BackgroundAppsSnapshot | None = None
        #: Background-app snapshots recorded per tick (in-memory, device-scoped)
        #: so per-episode contributor correlation can replay the window. Not
        #: persistent storage.
        self._background_history: list[tuple[float, BackgroundAppsSnapshot]] = []
        #: Most recent analysis outputs, retained so the UI can render a
        #: complete view-state without re-running analysis.
        self._last_evidence: tuple[PerformanceEvidence, ...] = ()
        self._last_events: tuple[PerformanceEvent, ...] = ()
        self._last_recovered_at: float | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def begin_session(self, device_serial: str | None, timestamp: float | None = None) -> None:
        self.session.begin_session(device_serial, timestamp)

    def end_session(self) -> None:
        """Close the live session: clear history and all live episode state."""
        self.session.clear()
        self.tracker.reset()
        self.episodes.reset()
        self._background_history = []
        self._last_evidence = ()
        self._last_events = ()
        self._last_recovered_at = None

    # ------------------------------------------------------------------
    # Ingestion (driven by the monitor's existing signals)
    # ------------------------------------------------------------------

    def ingest(
        self,
        *,
        cpu: CPUSnapshot | None = None,
        memory: MemorySnapshot | None = None,
        battery: BatterySnapshot | None = None,
        storage: StorageSnapshot | None = None,
        processes: ProcessSnapshot | None = None,
        network: NetworkSnapshot | None = None,
        background_apps: BackgroundAppsSnapshot | None = None,
        timestamp: float | None = None,
    ) -> OrchestratorResult:
        ts = timestamp if timestamp is not None else time.monotonic()
        cpu_pct = cpu_used_percent(cpu)
        mem_pct = memory_used_percent(memory)
        batt = battery_level_percent(battery)
        sto_pct = storage_used_percent(storage)
        proc = process_count(processes)
        rx, tx = network_throughput(network)

        # Unavailable metrics stay None: never fabricated as 0.
        self.session.record(
            cpu_used_percent=cpu_pct,
            memory_used_percent=mem_pct,
            battery_level_percent=batt,
            storage_used_percent=sto_pct,
            process_count=proc,
            network_rx_bytes_per_s=rx,
            network_tx_bytes_per_s=tx,
            timestamp=ts,
        )
        if background_apps is not None:
            self._background_apps = background_apps
            self._background_history.append((ts, background_apps))
            if len(self._background_history) > 600:
                self._background_history = self._background_history[-600:]

        return self._analyze(ts)

    # ------------------------------------------------------------------
    # Analysis + dedup
    # ------------------------------------------------------------------

    def _analyze(self, now: float) -> OrchestratorResult:
        cpu_win = self.session.window_for(PerformanceMetric.CPU.value)
        mem_win = self.session.window_for(PerformanceMetric.MEMORY.value)
        sto_win = self.session.window_for(PerformanceMetric.STORAGE.value)
        proc_win = self.session.window_for(PerformanceMetric.PROCESS_COUNT.value)

        cpu_a = self.analyzer.analyze_cpu(cpu_win, timestamp=now)
        mem_a = self.analyzer.analyze_memory(mem_win, timestamp=now)
        sto_a = self.analyzer.analyze_storage(sto_win, timestamp=now)
        proc_a = self.analyzer.analyze_process_pressure(proc_win, timestamp=now)

        all_evidence: list[PerformanceEvidence] = []
        conditions: list[tuple[str, DiagnosticFinding, str]] = []
        for analysis, metric in (
            (cpu_a, DiagnosticCategory.CPU.value),
            (mem_a, DiagnosticCategory.MEMORY.value),
            (sto_a, DiagnosticCategory.STORAGE.value),
            (proc_a, DiagnosticCategory.PROCESS.value),
        ):
            all_evidence.extend(analysis.evidence)
            for finding in analysis.findings:
                key = f"{finding.category.value}:{finding.severity.value[1]}"
                conditions.append((key, finding, metric))

        # Application correlation: consume already-resolved identity.
        app_loads = app_loads_from_background(self._last_background_apps())
        app_a = self.analyzer.analyze_application_pressure(app_loads, timestamp=now)
        all_evidence.extend(app_a.evidence)
        for finding in app_a.findings:
            if app_loads:
                key = f"app:{app_loads[0][0]}"
                conditions.append((key, finding, "application"))

        step = self.tracker.update(conditions, now)

        events: list[PerformanceEvent] = []
        for cond in step.started:
            events.append(self._event(cond, "started", now))
        for cond in step.recovered:
            events.append(self._event(cond, "recovered", now))
        for cond in step.active_persisted:
            events.append(self._event(cond, "active", now))
        if step.recovered:
            self._last_recovered_at = now

        findings = tuple(c.finding for c in step.started)
        self._last_evidence = tuple(all_evidence)

        # ------------------------------------------------------------------
        # Phase 5 — grouped episode lifecycle. The EpisodeTracker consumes the
        # already-normalized ConditionTracker transitions; no per-tick episode
        # events are emitted. When an episode actually closes, exactly ONE
        # recovery announcement is added to the existing event stream (which
        # the GUI adapter already records on the unified Timeline).
        # ------------------------------------------------------------------
        episode_recovery = self._update_episodes(step, now, all_evidence)
        if episode_recovery is not None:
            events.append(episode_recovery)

        # Accumulate lifecycle events (the tracker only emits transitions, so a
        # steady-state tick carries none — overwriting would erase earlier
        # STARTED/RECOVERED transitions from the view). Bounded to keep the
        # recent-events list small.
        if events:
            merged = list(self._last_events) + list(events)
            self._last_events = tuple(merged[-50:])

        return OrchestratorResult(
            evidence=tuple(all_evidence),
            findings=findings,
            events=tuple(events),
        )

    def _update_episodes(
        self,
        step: TrackerStep,
        now: float,
        evidence: Sequence[PerformanceEvidence],
    ) -> PerformanceEvent | None:
        """Feed one tick's condition transitions to the :class:`EpisodeTracker`.

        Returns the single recovery-announcement event when an episode closed
        this tick, else ``None``. Never emits while an episode is open.
        """
        pressured = sorted({cond.metric for cond in self.tracker.active_conditions})
        pressure_names = tuple(
            dict.fromkeys(_PRESSURE_NAME.get(metric, "process") for metric in pressured)
        )
        contributors_now = rank_contributors(
            self._background_apps,
            pressure_metrics=pressure_names,
            excluded=set(),
        )
        score = compute_score(self._deviations_snapshot())
        update = self.episodes.update(
            started=tuple(
                cond for cond in step.started if cond.metric in _EPISODE_METRICS
            ),
            recovered=tuple(
                cond for cond in step.recovered if cond.metric in _EPISODE_METRICS
            ),
            now=now,
            score=score.score,
            evidence=evidence,
            contributors=contributors_now,
        )
        if not update.closed or update.closed_record is None:
            return None
        return self._episode_recovery_event(update.closed_record, now)

    @staticmethod
    def _episode_recovery_event(record, now: float) -> PerformanceEvent:
        """One non-causal announcement for a recovered episode.

        The escalated severity and the deterministic episode id travel with the
        event; the id is identity vocabulary (``evidence_ids``), never embedded
        metrics. Purely observational — no cause is implied.
        """
        parts = [
            f"Conditions observed: {', '.join(record.condition_keys)}.",
            f"Affected metrics: {', '.join(record.metrics)}.",
        ]
        if (
            record.started_at is not None
            and record.recovered_at is not None
            and record.recovered_at >= record.started_at
        ):
            parts.append(
                f"Duration: {format_duration(record.recovered_at - record.started_at)}."
            )
        return PerformanceEvent(
            timestamp=now,
            event_type=PerformanceEventType.EPISODE_RECOVERY,
            severity=record.severity,
            title=f"Performance episode {record.episode_id} recovered",
            description=" ".join(parts),
            entity=None,
            evidence_ids=(record.episode_id,),
            device_serial=None,
        )

    def view_state(self) -> "PerformanceViewState":
        """Assemble the render-ready :class:`PerformanceViewState`.

        Pure and deterministic: it only reads the existing session, tracker,
        baseline and the retained last analysis. The GUI renders it; no
        analysis is performed in the presentation layer.
        """
        from .view import (
            METRIC_BATTERY,
            METRIC_CPU,
            METRIC_MEMORY,
            METRIC_STORAGE,
            AppCorrelation,
            EventRow,
            EvidenceRow,
            FindingView,
            PerformanceViewState,
            evidence_group,
        )

        metrics = {key: self._metric_view(key) for key in (
            METRIC_CPU, METRIC_MEMORY, METRIC_STORAGE, METRIC_BATTERY
        )}

        findings = tuple(
            FindingView(
                title=cond.finding.title,
                severity=cond.finding.severity.value[1],
                category=cond.finding.category.value,
                evidence=cond.finding.evidence,
                first_seen=cond.first_seen,
                phase=(
                    "ACTIVE"
                    if (cond.last_seen - cond.first_seen) >= self.analyzer.sustained_seconds
                    else "STARTED"
                ),
            )
            for cond in self.tracker.active_conditions
        )

        evidence = tuple(
            EvidenceRow(
                group=evidence_group(ev.kind),
                metric=ev.metric,
                statement=ev.statement,
                kind=ev.kind.value,
            )
            for ev in self._last_evidence
        )

        apps: list[AppCorrelation] = []
        bg = self._background_apps
        if bg is not None and bg.entries:
            ranked = sorted(
                bg.entries,
                key=lambda e: (e.cpu_percent or 0.0) + (e.memory_percent or 0.0),
                reverse=True,
            )[:5]
            for entry in ranked:
                apps.append(
                    AppCorrelation(
                        package=entry.package_name,
                        label=entry.label,
                        cpu_percent=entry.cpu_percent,
                        memory_percent=entry.memory_percent,
                        process_count=len(entry.pids),
                        state=entry.state.value if entry.state else None,
                    )
                )

        events = tuple(
            EventRow(
                title=ev.title,
                severity=ev.severity,
                phase=(
                    "recovered"
                    if "recovered" in ev.title
                    else "active"
                    if "active" in ev.title
                    else "started"
                ),
                monotonic=ev.timestamp,
            )
            for ev in self._last_events
        )

        history: dict[str, tuple[float, ...]] = {}
        for key in (METRIC_CPU, METRIC_MEMORY, METRIC_STORAGE, METRIC_BATTERY):
            win = self.session.window_for(key)
            history[key] = tuple(win.values(key)) if key in win.metrics() else ()

        # ------------------------------------------------------------------
        # Phase 4 — explainable intelligence (all pure, derived above)
        # ------------------------------------------------------------------
        deviations = self._deviations_snapshot()

        trends: dict[str, str] = {}
        for key in (METRIC_CPU, METRIC_MEMORY, METRIC_STORAGE, METRIC_BATTERY):
            trends[key] = self._trend_for(key)
        trends["process"] = self._trend_for_process()

        score = compute_score(deviations)

        pressured = {cond.metric for cond in self.tracker.active_conditions}
        contributors = rank_contributors(
            self._last_background_apps(),
            pressure_metrics=tuple(pressured),
            excluded=set(),
        )

        explanations, recommendation_parts = self._build_explanations(
            deviations, trends, contributors
        )

        # ------------------------------------------------------------------
        # Phase 5 — historical episodes + investigation (all pure)
        # ------------------------------------------------------------------
        active_episodes, recent_episodes = self._build_episodes()
        all_episodes = list(active_episodes) + list(recent_episodes)
        current_episode = (
            active_episodes[0]
            if active_episodes
            else (recent_episodes[0] if recent_episodes else None)
        )

        historical_comparison = None
        investigation_summary = None
        if current_episode is not None:
            metric = current_episode.metric
            baseline_obj = self._baseline_for(metric)
            comparable = find_comparable(
                all_episodes, metric=metric, exclude=current_episode
            )
            historical_comparison = build_historical_comparison(
                episode=current_episode, baseline=baseline_obj, comparable=comparable
            )
            dev = deviations.get(metric)
            if dev is None and metric == "application":
                dev = deviations.get("process")
            top_corr = (
                current_episode.contributor_correlation[0]
                if current_episode.contributor_correlation
                else None
            )
            trend = trends.get(metric) or trends.get("process")
            recs = build_recommendations(
                metric, current_episode.contributors[:1] if current_episode.contributors else ()
            )
            investigation_summary = build_investigation_summary(
                episode=current_episode,
                deviation=dev,
                historical=historical_comparison,
                top_correlation=top_corr,
                trend=trend,
                recommendation=recs[0] if recs else "",
            )

        return PerformanceViewState(
            overall_state=self._overall_state(),
            metrics=metrics,
            findings=findings,
            evidence=evidence,
            app_correlations=tuple(apps),
            events=events,
            history=history,
            performance_score=score,
            metric_deviations=deviations,
            trends=trends,
            contributors=contributors,
            explanations=tuple(explanations),
            investigation_recommendations=tuple(dict.fromkeys(recommendation_parts)),
            active_episodes=tuple(active_episodes),
            recent_episodes=tuple(recent_episodes),
            episode_count=len(all_episodes),
            current_episode=current_episode,
            investigation_summary=investigation_summary,
            historical_comparison=historical_comparison,
        )

    def _metric_view(self, key: str) -> "MetricView":
        from .view import (
            _LABELS,
            _THRESHOLDS,
            METRIC_BATTERY,
            MetricView,
            condition_for,
        )

        win = self.session.window_for(key)
        if win.is_empty or key not in win.metrics():
            return MetricView(
                key=key, label=_LABELS[key], unit="%", current=None,
                baseline=None, delta=None, occupancy=None,
                condition="UNKNOWN", evidence=None,
            )
        values = win.values(key)
        current = win.latest(key)
        baseline = BaselineCalculator.from_window(key, win)
        delta = win.change_from_baseline(key, baseline.mean)
        if key == METRIC_BATTERY:
            warn = BATTERY_LEVEL_ELEVATED_PERCENT
            crit = BATTERY_LEVEL_HIGH_PERCENT
            if current is None:
                condition = "UNKNOWN"
            elif current <= crit:
                condition = "CRITICAL"
            elif current <= warn:
                condition = "ELEVATED"
            else:
                condition = "NORMAL"
            occupancy = sum(1 for v in values if v <= warn) / len(values)
        else:
            warn, crit = _THRESHOLDS[key]
            condition = condition_for(key, current, warn, crit)
            occupancy = win.threshold_occupancy(key, warn)
        rep = None
        for ev in self._last_evidence:
            if ev.metric == key and ev.kind in (
                EvidenceKind.THRESHOLD_OCCUPANCY,
                EvidenceKind.STATISTIC,
            ):
                rep = ev.statement
                break
        return MetricView(
            key=key, label=_LABELS[key], unit="%", current=current,
            baseline=baseline, delta=delta, occupancy=occupancy,
            condition=condition, evidence=rep,
        )

    def _deviation_for(self, key: str) -> MetricDeviation:
        """Phase 4A: baseline deviation for a canonical metric."""
        from .view import _LABELS, _THRESHOLDS

        win = self.session.window_for(key)
        if win.is_empty or key not in win.metrics():
            baseline = None
            current = None
        else:
            current = win.latest(key)
            try:
                baseline = BaselineCalculator.from_window(key, win)
            except ValueError:
                baseline = None
        if key == METRIC_BATTERY:
            warn = BATTERY_LEVEL_ELEVATED_PERCENT
            crit = BATTERY_LEVEL_HIGH_PERCENT
            higher_is_worse = False
        else:
            warn, crit = _THRESHOLDS[key]
            higher_is_worse = True
        return compute_deviation(
            metric=key, label=_LABELS[key], current=current,
            baseline=baseline, warn=warn, crit=crit, higher_is_worse=higher_is_worse,
        )

    def _deviations_snapshot(self) -> dict[str, MetricDeviation]:
        """Phase 4A: baseline deviations for every supported metric.

        Shared by ``view_state`` and the per-tick episode score feed so both
        read the identical derivation.
        """
        from .view import METRIC_BATTERY, METRIC_CPU, METRIC_MEMORY, METRIC_STORAGE

        deviations: dict[str, MetricDeviation] = {}
        for key in (METRIC_CPU, METRIC_MEMORY, METRIC_STORAGE, METRIC_BATTERY):
            deviations[key] = self._deviation_for(key)
        deviations["process"] = self._process_deviation()
        return deviations

    def _process_deviation(self) -> MetricDeviation:
        """Phase 4A: process-count deviation (no baseline; band from thresholds)."""
        win = self.session.window_for(PerformanceMetric.PROCESS_COUNT.value)
        if win.is_empty or PerformanceMetric.PROCESS_COUNT.value not in win.metrics():
            current = None
        else:
            current = win.latest(PerformanceMetric.PROCESS_COUNT.value)
        return compute_deviation(
            metric="process", label="Process count", current=current,
            baseline=None, warn=self.analyzer.proc_warn,
            crit=self.analyzer.proc_crit, higher_is_worse=True,
        )

    def _trend_for(self, key: str) -> str:
        """Phase 4C: trend direction for a canonical metric."""
        from .view import _THRESHOLDS

        win = self.session.window_for(key)
        values = (
            list(win.values(key))
            if not win.is_empty and key in win.metrics()
            else []
        )
        if key == METRIC_BATTERY:
            warn = BATTERY_LEVEL_ELEVATED_PERCENT
            higher_is_worse = False
            recovering_reference = None
        else:
            warn, _ = _THRESHOLDS[key]
            higher_is_worse = True
            recovering_reference = warn
        return classify_trend(
            values, higher_is_worse=higher_is_worse,
            recovering_reference=recovering_reference,
        )

    def _trend_for_process(self) -> str:
        """Phase 4C: trend direction for process count."""
        metric = PerformanceMetric.PROCESS_COUNT.value
        win = self.session.window_for(metric)
        values = (
            list(win.values(metric))
            if not win.is_empty and metric in win.metrics()
            else []
        )
        return classify_trend(
            values, higher_is_worse=True,
            recovering_reference=self.analyzer.proc_warn,
        )

    def _build_explanations(
        self,
        deviations: dict[str, MetricDeviation],
        trends: dict[str, str],
        contributors: tuple[ContributorCandidate, ...],
    ) -> tuple[list, list[str]]:
        """Phase 4E/F: per-condition explanations + investigation recommendations."""
        explanations: list = []
        recommendation_parts: list[str] = []
        for cond in self.tracker.active_conditions:
            metric = cond.metric
            dev: MetricDeviation | None
            if metric in deviations:
                dev = deviations[metric]
            elif metric == "application":
                dev = deviations.get("process")
            else:
                dev = None
            trend = trends.get(metric) or trends.get("process")
            rel = metric if metric in ("cpu", "memory", "storage", "process") else "process"
            cond_contribs = tuple(
                c for c in contributors if c.relevant_metric == rel
            ) or contributors[:1]
            expl = build_explanation(
                metric=metric, title=cond.finding.title,
                deviation=dev, trend=trend, contributors=cond_contribs,
            )
            explanations.append(expl)
            recommendation_parts.extend(expl.recommendations)
        return explanations, recommendation_parts

    def _build_episodes(self) -> tuple[list[PerformanceEpisode], list[PerformanceEpisode]]:
        """Phase 5: render grouped active + recently-recovered episodes.

        The :class:`EpisodeTracker` owns the temporal grouping and aggregates;
        this only renders them into frozen models from recorded samples. The
        open episode renders with ``current_time`` (duration so far), the
        completed ones newest-first, deterministically.
        """
        current_time = self._latest_timestamp()
        active: list[PerformanceEpisode] = []

        open_record = self.episodes.open_record()
        if open_record is not None:
            lifecycle = (
                EpisodeLifecycle.STARTED.value
                if self.episodes.open_just_started
                else EpisodeLifecycle.ACTIVE.value
            )
            active.append(
                build_grouped_episode(
                    episode_id=open_record.episode_id,
                    condition_keys=open_record.condition_keys,
                    metrics=open_record.metrics,
                    severity=open_record.severity,
                    first_seen=open_record.started_at,
                    last_seen=None,
                    is_active=True,
                    current_time=current_time,
                    session=self.session,
                    background_history=self._background_history,
                    excluded=set(),
                    evidence=open_record.evidence,
                    lifecycle=lifecycle,
                    score_at_start=open_record.score_at_start,
                    score_min=open_record.score_min,
                    contributors=open_record.contributors,
                )
            )

        recent = [
            self._render_completed_episode(record)
            for record in reversed(self.episodes.completed_episodes)
        ]
        return active, recent

    def _render_completed_episode(self, record) -> PerformanceEpisode:
        return build_grouped_episode(
            episode_id=record.episode_id,
            condition_keys=record.condition_keys,
            metrics=record.metrics,
            severity=record.severity,
            first_seen=record.started_at,
            last_seen=record.recovered_at,
            is_active=False,
            current_time=None,
            session=self.session,
            background_history=self._background_history,
            excluded=set(),
            evidence=record.evidence,
            lifecycle=EpisodeLifecycle.RECOVERED.value,
            score_at_start=record.score_at_start,
            score_min=record.score_min,
            score_at_recovery=record.score_at_recovery,
            contributors=record.contributors,
        )

    def _baseline_for(self, metric: str):

        wkey = _WINDOW_KEY.get(metric, metric)
        win = self.session.window_for(wkey)
        if win.is_empty or wkey not in win.metrics():
            return None
        try:
            return BaselineCalculator.from_window(wkey, win)
        except ValueError:
            return None

    def _overall_state(self) -> str:
        from .view import (
            METRIC_CPU,
            METRIC_MEMORY,
            METRIC_STORAGE,
            RECOVERING_WINDOW_S,
            STATE_APPLICATION_PRESSURE,
            STATE_CPU_PRESSURE,
            STATE_MEMORY_PRESSURE,
            STATE_MULTI_METRIC,
            STATE_NORMAL,
            STATE_PROCESS_PRESSURE,
            STATE_RECOVERING,
            STATE_STORAGE_PRESSURE,
        )

        pressured = {cond.metric for cond in self.tracker.active_conditions}
        if pressured:
            if len(pressured) >= 2:
                return STATE_MULTI_METRIC
            mapping = {
                METRIC_CPU: STATE_CPU_PRESSURE,
                METRIC_MEMORY: STATE_MEMORY_PRESSURE,
                METRIC_STORAGE: STATE_STORAGE_PRESSURE,
                "process": STATE_PROCESS_PRESSURE,
                "application": STATE_APPLICATION_PRESSURE,
            }
            return mapping.get(next(iter(pressured)), STATE_MULTI_METRIC)
        latest_ts = self._latest_timestamp()
        if (
            self._last_recovered_at is not None
            and latest_ts is not None
            and (latest_ts - self._last_recovered_at) <= RECOVERING_WINDOW_S
        ):
            return STATE_RECOVERING
        return STATE_NORMAL

    def _latest_timestamp(self) -> float | None:
        for key in (
            "cpu", "memory", "storage", "battery",
        ):
            win = self.session.window_for(key)
            samples = win.iter_samples()
            if samples:
                return samples[-1].timestamp
        return None

    def _last_background_apps(self) -> BackgroundAppsSnapshot | None:
        return self._background_apps

    def set_background_apps(self, background_apps: BackgroundAppsSnapshot | None) -> None:
        """Store the latest already-resolved background-app snapshot."""
        self._background_apps = background_apps

    @property
    def background_apps(self) -> BackgroundAppsSnapshot | None:
        """The most recent already-resolved background-app snapshot."""
        return self._background_apps

    @staticmethod
    def _event(cond: "ActiveCondition", phase: str, now: float) -> PerformanceEvent:
        etype = _METRIC_EVENT_TYPE.get(cond.metric, PerformanceEventType.ANOMALY)
        return PerformanceEvent(
            timestamp=now,
            event_type=etype,
            severity=cond.finding.severity.value[1],
            title=f"{cond.finding.title} ({phase})",
            description=cond.finding.evidence,
            entity=cond.metric,
            evidence_ids=(cond.key,),
            device_serial=None,
        )


__all__ = ["OrchestratorResult", "PerformanceOrchestrator", "PerformanceViewState"]
