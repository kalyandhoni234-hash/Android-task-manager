"""Phase 5 tests: historical performance & investigation episodes.

Covers episode lifecycle, peak/duration, baseline + historical comparison,
contributor correlation, investigation summary, view-state integration, GUI
rendering, disconnect/reconnect semantics, and an architecture/honesty audit.
Pure domain tests run without Qt; GUI rendering tests import PySide6.
"""

from __future__ import annotations

import os
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from android_task_manager.background.models import (
    BackgroundAppEntry,
    BackgroundAppsSnapshot,
    BackgroundAppState,
)
from android_task_manager.diagnostics.models import (
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticSeverity,
)
from android_task_manager.performance import (
    EPISODE_RETENTION,
    EVIDENCE_RETENTION,
    Baseline,
    EpisodeTracker,
    PerformanceOrchestrator,
    PerformanceSession,
    build_episode,
    build_grouped_episode,
    build_historical_comparison,
    build_investigation_summary,
    correlate_contributors,
)
from android_task_manager.performance.episodes import format_duration
from android_task_manager.performance.tracker import ActiveCondition

PERF_DIR = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "android_task_manager" / "performance"
)


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------

def _cpu_snap(pct, ts):
    from android_task_manager.cpu.models import CPUSnapshot
    return CPUSnapshot(timestamp=ts, aggregate_utilization_percent=pct, cores=())


def _mem_snap(pct, ts):
    from android_task_manager.memory.models import MemorySnapshot
    total = 1000
    avail = int(round(total * (1 - pct / 100.0)))
    return MemorySnapshot(timestamp=ts, total_kb=total, free_kb=0, available_kb=avail,
                          buffers_kb=0, cached_kb=0, swap_cached_kb=0)


def _bg_entry(pkg, label, cpu, mem, uid=1, pids=(1,)):
    return BackgroundAppEntry(package_name=pkg, label=label, uid=uid, pids=pids,
                              cpu_percent=cpu, memory_percent=mem, memory_kb=10,
                              state=BackgroundAppState.BACKGROUND)


def _bg_hist(n, *, heavy_top_missing=None):
    """Background history of *n* ticks; heavy is top unless index in missing."""
    missing = heavy_top_missing or set()
    out = []
    for i in range(n):
        light_cpu = 80.0 if i in missing else 5.0
        out.append((float(i), BackgroundAppsSnapshot(timestamp=float(i), entries=[
            _bg_entry("com.heavy", "Heavy", 40.0, 20.0, uid=1),
            _bg_entry("com.light", "Light", light_cpu, 5.0, uid=2),
        ])))
    return out


def _finding(sev="warning", cat=DiagnosticCategory.CPU, title="CPU pressure"):
    return DiagnosticFinding(
        severity=DiagnosticSeverity.WARNING if sev == "warning" else DiagnosticSeverity.CRITICAL,
        category=cat, title=title, what="w", why="y", evidence="e",
        recommended_action="a",
    )


def _active_condition(key="cpu:warning", metric="cpu", first=1.0, last=5.0,
                      sev="warning", cat=DiagnosticCategory.CPU, title="CPU pressure"):
    return ActiveCondition(
        key=key, finding=_finding(sev, cat, title), metric=metric,
        first_seen=first, last_seen=last,
    )


def _baseline(metric="cpu", median=60.0, p95=76.0, count=20):
    return Baseline(metric=metric, count=count, mean=median, median=median,
                   p95=p95, minimum=median - 5, maximum=p95 + 5, stddev=3.0)


def _rec(session, *, cpu=None, memory=None, storage=None, battery=None,
         process=None, ts=0.0):
    session.record(
        cpu_used_percent=cpu, memory_used_percent=memory,
        battery_level_percent=battery, storage_used_percent=storage,
        process_count=process, timestamp=ts,
    )


# --------------------------------------------------------------------------
# 1-2. Lifecycle via orchestrator
# --------------------------------------------------------------------------

def _drive_cpu(orchestrator, pcts):
    for i, p in enumerate(pcts):
        orchestrator.ingest(cpu=_cpu_snap(p, float(i)), timestamp=float(i))


def _orchestrator():
    # Small window so recovery occurs after a short low-pressure run.
    return PerformanceOrchestrator(
        session=PerformanceSession(cpu_max_samples=8, memory_max_samples=8,
                                   storage_max_samples=8),
    )


def test_started_active_recovered_episode():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_cpu(o, [95, 96, 97, 96, 95, 10, 11, 12, 10, 9, 8, 7, 6, 5, 4])
    state = o.view_state()
    assert len(state.recent_episodes) == 1
    ep = state.recent_episodes[0]
    assert ep.is_active is False
    assert ep.recovered_at is not None
    assert ep.started_at is not None


def test_active_incomplete_episode():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_cpu(o, [95, 96, 97, 96, 95])
    state = o.view_state()
    assert len(state.active_episodes) == 1
    ep = state.active_episodes[0]
    assert ep.is_active is True
    assert ep.recovered_at is None


# --------------------------------------------------------------------------
# 3-4. Peak detection
# --------------------------------------------------------------------------

def test_peak_value_and_timestamp():
    session = PerformanceSession()
    for i, v in enumerate([61, 68, 79, 87, 94, 91, 84]):
        _rec(session, cpu=v, ts=float(i))
    ep = build_episode(
        condition_key="cpu:warning", category="cpu", severity="warning",
        metric="cpu", first_seen=0.0, last_seen=6.0, is_active=False,
        current_time=None, session=session,
    )
    assert ep.peak_value == pytest.approx(94.0)
    assert ep.peak_timestamp == pytest.approx(4.0)


# --------------------------------------------------------------------------
# 5-8. Duration / defensive timestamps
# --------------------------------------------------------------------------

def test_duration_recovered():
    session = PerformanceSession()
    ep = build_episode(
        condition_key="cpu:warning", category="cpu", severity="warning",
        metric="cpu", first_seen=10.0, last_seen=14.0, is_active=False,
        current_time=None, session=session,
    )
    assert ep.duration == pytest.approx(4.0)


def test_missing_start_timestamp_duration_none():
    session = PerformanceSession()
    ep = build_episode(
        condition_key="cpu:warning", category="cpu", severity="warning",
        metric="cpu", first_seen=None, last_seen=14.0, is_active=False,
        current_time=None, session=session,
    )
    assert ep.duration is None


def test_non_monotonic_timestamps_do_not_corrupt():
    session = PerformanceSession()
    for ts, v in [(3.0, 70.0), (1.0, 90.0), (2.0, 50.0)]:
        _rec(session, cpu=v, ts=ts)
    ep = build_episode(
        condition_key="cpu:warning", category="cpu", severity="warning",
        metric="cpu", first_seen=1.0, last_seen=3.0, is_active=False,
        current_time=None, session=session,
    )
    assert ep.peak_value == pytest.approx(90.0)


def test_no_negative_duration():
    session = PerformanceSession()
    ep = build_episode(
        condition_key="cpu:warning", category="cpu", severity="warning",
        metric="cpu", first_seen=20.0, last_seen=10.0, is_active=False,
        current_time=None, session=session,
    )
    assert ep.duration is None


# --------------------------------------------------------------------------
# 9-12. Baseline + historical comparison
# --------------------------------------------------------------------------

def _episode_for(metric, peak):
    session = PerformanceSession()
    if metric == "process":
        for i in range(6):
            _rec(session, process=int(peak) if i == 3 else 10, ts=float(i))
    else:
        for i in range(6):
            val = peak if i == 3 else 30.0
            _rec(session, cpu=val if metric == "cpu" else None,
                 memory=val if metric == "memory" else None,
                 storage=val if metric == "storage" else None,
                 ts=float(i))
    return build_episode(
        condition_key=f"{metric}:warning", category=metric, severity="warning",
        metric=metric, first_seen=0.0, last_seen=5.0, is_active=False,
        current_time=None, session=session,
    )


def test_baseline_comparison_sufficient():
    ep = _episode_for("memory", 94.0)
    baseline = _baseline("memory", median=61.0, p95=76.0)
    comp = build_historical_comparison(episode=ep, baseline=baseline, comparable=())
    assert comp.baseline_available is True
    assert comp.peak_vs_baseline_p95_pp == pytest.approx(94.0 - 76.0, abs=0.05)


def test_insufficient_historical_data():
    ep = _episode_for("memory", 94.0)
    comp = build_historical_comparison(episode=ep, baseline=None, comparable=())
    assert comp.baseline_available is False
    assert comp.sufficient is False
    assert "HISTORICAL_DATA_INSUFFICIENT" in comp.message


def test_historical_comparison_with_comparable():
    ep = _episode_for("memory", 94.0)
    others = [
        _episode_for("memory", 80.0),
        _episode_for("memory", 80.0),
    ]
    comp = build_historical_comparison(episode=ep, baseline=_baseline("memory"),
                                       comparable=others)
    assert comp.comparable_episode_count == 2
    # Default episodes span first_seen 0..last_seen 5 -> duration 5.0 (median 5).
    assert comp.previous_median_duration == pytest.approx(5.0)


def test_multiple_comparable_median():
    ep = _episode_for("memory", 94.0)
    others = [_episode_for("memory", 80.0) for _ in range(3)]
    comp = build_historical_comparison(episode=ep, baseline=_baseline("memory"),
                                       comparable=others)
    assert comp.previous_median_duration == pytest.approx(5.0)


# --------------------------------------------------------------------------
# 13-16. Per-metric episodes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("metric,setter", [
    ("cpu", "cpu_used_percent"),
    ("memory", "memory_used_percent"),
    ("storage", "storage_used_percent"),
])
def test_canonical_metric_episode(metric, setter):
    session = PerformanceSession()
    for i in range(6):
        val = 90.0 if i == 3 else 30.0
        _rec(session, cpu=val if metric == "cpu" else None,
             memory=val if metric == "memory" else None,
             storage=val if metric == "storage" else None,
             ts=float(i))
    ep = build_episode(
        condition_key=f"{metric}:warning", category=metric, severity="warning",
        metric=metric, first_seen=0.0, last_seen=5.0, is_active=False,
        current_time=None, session=session,
    )
    assert ep.peak_value == pytest.approx(90.0)


def test_process_pressure_episode():
    ep = _episode_for("process", 450)
    assert ep.peak_value == 450.0


# --------------------------------------------------------------------------
# 17. Simultaneous overlapping conditions form ONE episode
# --------------------------------------------------------------------------

def test_simultaneous_conditions_form_one_episode():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    for i in range(8):
        o.ingest(cpu=_cpu_snap(95.0 + (i % 3), float(i)),
                 memory=_mem_snap(92.0 + (i % 3), float(i)),
                 timestamp=float(i))
    state = o.view_state()
    # Overlapping pressure windows group into ONE episode, never one per metric.
    assert len(state.active_episodes) == 1
    ep = state.active_episodes[0]
    assert set(ep.metrics) == {"cpu", "memory"}
    assert len(ep.condition_keys) == 2
    assert {k.split(":")[0] for k in ep.condition_keys} == {"cpu", "memory"}


# --------------------------------------------------------------------------
# 18-22. Contributor correlation
# --------------------------------------------------------------------------

def test_contributor_frequency_present_in_all():
    hist = _bg_hist(10)
    corr = correlate_contributors(hist, pressure_metrics=("cpu",))
    heavy = next(c for c in corr if c.package == "com.heavy")
    assert heavy.samples_present == 10
    assert heavy.samples_total == 10


def test_repeated_top_contributor():
    hist = _bg_hist(10, heavy_top_missing={2, 5, 8})
    corr = correlate_contributors(hist, pressure_metrics=("cpu",))
    heavy = next(c for c in corr if c.package == "com.heavy")
    assert heavy.times_top == 7
    assert heavy.samples_present == 10


def test_missing_application_label():
    snap = [(0.0, BackgroundAppsSnapshot(timestamp=0.0, entries=[
        _bg_entry("com.unknown", None, 40.0, 20.0, uid=3),
    ]))]
    corr = correlate_contributors(snap, pressure_metrics=("cpu",))
    assert corr[0].label is None
    assert corr[0].package == "com.unknown"


def test_unknown_application_identity_excluded():
    snap = [(0.0, BackgroundAppsSnapshot(timestamp=0.0, entries=[
        _bg_entry("", "Phantom", 90.0, 80.0, uid=9),
        _bg_entry("com.real", "Real", 10.0, 5.0, uid=1),
    ]))]
    corr = correlate_contributors(snap, pressure_metrics=("cpu",))
    packages = {c.package for c in corr}
    assert "" not in packages
    assert "com.real" in packages


def test_system_application_exclusion():
    hist = _bg_hist(5)
    corr = correlate_contributors(hist, pressure_metrics=("cpu",), excluded={"com.light"})
    packages = {c.package for c in corr}
    assert "com.light" not in packages
    assert "com.heavy" in packages


# --------------------------------------------------------------------------
# 23-25. Investigation summary
# --------------------------------------------------------------------------

def test_investigation_summary_content():
    session = PerformanceSession()
    for i in range(6):
        val = 94.0 if i == 3 else 30.0
        _rec(session, memory=val, ts=float(i))
    hist = _bg_hist(10)
    ep2 = build_episode(
        condition_key="memory:warning", category="memory", severity="warning",
        metric="memory", first_seen=0.0, last_seen=5.0, is_active=False,
        current_time=None, session=session, background_history=hist,
    )
    baseline = _baseline("memory", median=61.0, p95=76.0)
    comp = build_historical_comparison(episode=ep2, baseline=baseline, comparable=())
    summary = build_investigation_summary(
        episode=ep2, deviation=None, historical=comp,
        top_correlation=ep2.contributor_correlation[0] if ep2.contributor_correlation else None,
        trend="DEGRADING", recommendation="Inspect Heavy process/application details.",
    )
    blob = " ".join(summary.evidence_bullets).lower()
    assert "94.0" in blob
    assert summary.status == "RECOVERED"
    assert summary.duration_text == format_duration(5.0)


def test_investigation_summary_no_causal_wording():
    ep = _episode_for("memory", 94.0)
    comp = build_historical_comparison(episode=ep, baseline=_baseline("memory"), comparable=())
    summary = build_investigation_summary(
        episode=ep, deviation=None, historical=comp,
        top_correlation=ep.contributor_correlation[0] if ep.contributor_correlation else None,
        recommendation="Inspect the top memory-contributing application.",
    )
    blob = " ".join(summary.evidence_bullets).lower()
    for banned in ("caused", "causing", "responsible", "definitely malicious",
                   "force-stop", "kill"):
        assert banned not in blob


def test_investigation_summary_deterministic():
    ep = _episode_for("memory", 94.0)
    comp = build_historical_comparison(episode=ep, baseline=_baseline("memory"), comparable=())
    a = build_investigation_summary(episode=ep, deviation=None, historical=comp)
    b = build_investigation_summary(episode=ep, deviation=None, historical=comp)
    assert a == b


# --------------------------------------------------------------------------
# 26. View-state integration
# --------------------------------------------------------------------------

def test_view_state_includes_episode_fields():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_cpu(o, [95, 96, 97, 96, 95])
    state = o.view_state()
    assert state.episode_count >= 1
    assert state.current_episode is not None
    assert state.investigation_summary is not None
    assert state.historical_comparison is not None
    assert state.active_episodes[0].condition_key.startswith("cpu")


# --------------------------------------------------------------------------
# 27-30. GUI rendering + disconnect/reconnect
# --------------------------------------------------------------------------

def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_active_episode_renders_in_page():
    pytest.importorskip("PySide6")
    _app()
    from android_task_manager.gui.performance_page import PerformancePage

    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_cpu(o, [95, 96, 97, 96, 95])
    page = PerformancePage()
    page.refresh(o.view_state(), True)
    assert page._episodes_layout.count() >= 1


def test_recovered_episode_renders_in_page():
    pytest.importorskip("PySide6")
    _app()
    from android_task_manager.gui.performance_page import PerformancePage

    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_cpu(o, [95, 96, 97, 96, 95, 10, 11, 12, 10, 9, 8, 7, 6, 5, 4])
    page = PerformancePage()
    page.refresh(o.view_state(), True)
    assert page._episodes_layout.count() >= 1


def test_disconnect_clears_episodes():
    pytest.importorskip("PySide6")
    _app()
    from android_task_manager.gui.performance_page import PerformancePage

    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_cpu(o, [95, 96, 97, 96, 95])
    page = PerformancePage()
    page.refresh(o.view_state(), True)
    page.refresh(o.view_state(), False)
    # After disconnect the box is cleared (empty placeholder added = 1 widget).
    assert page._episodes_layout.count() == 1


def test_reconnect_cannot_resurrect_stale_state():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_cpu(o, [95, 96, 97, 96, 95, 10, 11, 12, 10, 9, 8, 7, 6, 5, 4])
    assert len(o.view_state().recent_episodes) == 1
    o.end_session()
    o.begin_session("SERIAL2", timestamp=100.0)
    state = o.view_state()
    assert state.active_episodes == ()
    assert state.recent_episodes == ()
    assert state.episode_count == 0


# --------------------------------------------------------------------------
# 31. Timeline event deduplication
# --------------------------------------------------------------------------

def test_sustained_pressure_single_started_event():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    started = []
    for i in range(30):
        res = o.ingest(cpu=_cpu_snap(95.0 + (i % 3), float(i)), timestamp=float(i))
        started.extend(res.events)
    assert len(started) == 1  # exactly one STARTED, no per-tick events


# --------------------------------------------------------------------------
# 32. Existing Phase 1-4 regression still present
# --------------------------------------------------------------------------

def test_phase4_surface_still_present():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_cpu(o, [95, 96, 97, 96, 95])
    state = o.view_state()
    assert state.performance_score is not None
    assert state.explanations
    assert state.investigation_recommendations


# --------------------------------------------------------------------------
# 33+. Grouped episode lifecycle (Phase 5 continuation)
# --------------------------------------------------------------------------

def _drive_ticks(o, ticks):
    """ticks: list of dicts with optional 'cpu'/'memory' percents.

    A small deterministic jitter is added because the underlying
    ``MetricHistory`` retains *changes* — a perfectly flat series collapses to
    a single window sample (the same convention the earlier phase tests use).
    """
    for i, tick in enumerate(ticks):
        jitter = ((i % 3) - 1) * 0.5
        o.ingest(
            cpu=_cpu_snap(tick["cpu"] + jitter, float(i)) if "cpu" in tick else None,
            memory=_mem_snap(tick["memory"] + jitter, float(i)) if "memory" in tick else None,
            timestamp=float(i),
        )


def test_first_tick_lifecycle_started_then_active():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    # Fewer than analyzer.min_samples -> evidence only, no condition/episode.
    _drive_ticks(o, [{"cpu": 95.0}] * 3)
    assert o.view_state().active_episodes == ()
    # The tick that produces the first finding opens the episode (STARTED).
    o.ingest(cpu=_cpu_snap(96.0, 3.0), timestamp=3.0)
    ep = o.view_state().active_episodes[0]
    assert ep.episode_id == "P-001"
    assert ep.lifecycle == "STARTED"
    # Any later tick renders the open episode as ACTIVE.
    o.ingest(cpu=_cpu_snap(97.0, 4.0), timestamp=4.0)
    assert o.view_state().active_episodes[0].lifecycle == "ACTIVE"


def test_sustained_condition_no_duplicate_episodes():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    for i in range(12):
        o.ingest(cpu=_cpu_snap(95.0 + (i % 3), float(i)), timestamp=float(i))
    state = o.view_state()
    assert len(state.active_episodes) == 1
    assert state.active_episodes[0].episode_id == "P-001"
    assert state.episode_count == 1


def test_one_condition_recovers_while_other_remains_active():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_ticks(o, [{"cpu": 95.0, "memory": 93.0}] * 6 + [{"cpu": 96.0}] * 6)
    state = o.view_state()
    # Memory recovered; the episode must stay ACTIVE and retain both metrics.
    assert len(state.active_episodes) == 1
    ep = state.active_episodes[0]
    assert ep.is_active is True
    assert ep.recovered_at is None
    assert set(ep.metrics) == {"cpu", "memory"}
    assert {k.split(":")[0] for k in ep.condition_keys} == {"cpu", "memory"}


def test_episode_closes_only_after_all_conditions_recover():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_ticks(
        o,
        # Both conditions active...
        [{"cpu": 95.0, "memory": 93.0}] * 6
        # ...memory recovers (fresh low samples evict the breach from its
        # bounded window) while CPU pressure continues...
        + [{"cpu": 96.0, "memory": 20.0}] * 10
        # ...and finally CPU recovers too.
        + [{"cpu": 12.0, "memory": 20.0}] * 10,
    )
    state = o.view_state()
    assert state.active_episodes == ()
    assert len(state.recent_episodes) == 1
    ep = state.recent_episodes[0]
    assert ep.is_active is False
    assert ep.recovered_at is not None
    assert ep.lifecycle == "RECOVERED"
    # All involved metrics/conditions are retained after recovery.
    assert set(ep.metrics) == {"cpu", "memory"}
    assert {k.split(":")[0] for k in ep.condition_keys} == {"cpu", "memory"}


def test_non_overlapping_conditions_create_new_episode():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_ticks(
        o,
        [{"cpu": 95.0}] * 5
        + [{"cpu": 11.0}] * 10
        + [{"memory": 94.0}] * 5
        + [{"memory": 20.0}] * 10,
    )
    state = o.view_state()
    assert state.active_episodes == ()
    ids = [e.episode_id for e in state.recent_episodes]
    assert ids == ["P-002", "P-001"]  # deterministic newest-first ordering
    first, second = state.recent_episodes[1], state.recent_episodes[0]
    assert first.metrics == ("cpu",)
    assert second.metrics == ("memory",)


def test_highest_severity_retained_after_escalation():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    # CPU 75% -> ELEVATED (warning); then 96% -> CRITICAL; then recovery.
    _drive_ticks(o, [{"cpu": 75.0}] * 5 + [{"cpu": 96.0}] * 4 + [{"cpu": 10.0}] * 10)
    ep = o.view_state().recent_episodes[0]
    # One episode only: the escalation joined the open window.
    assert len(o.view_state().recent_episodes) == 1
    assert ep.severity == "critical"  # highest observed level retained


def test_contributors_preserved_on_completed_episode():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    snapshot = _bg_hist(1)[0][1]
    for i in range(5):
        # Snapshot lands on tick 4, i.e. DURING the open episode window.
        o.ingest(
            cpu=_cpu_snap(95.0 + (i % 3), float(i)),
            background_apps=snapshot if i == 4 else None,
            timestamp=float(i),
        )
    for i in range(10):
        o.ingest(cpu=_cpu_snap(10.0 + (i % 3), 5.0 + i), timestamp=5.0 + i)
    ep = o.view_state().recent_episodes[0]
    assert ep.lifecycle == "RECOVERED"
    packages = {c.package for c in ep.contributors}
    assert "com.heavy" in packages
    assert any(c.package == "com.heavy" for c in ep.contributor_correlation)


def test_deterministic_ids_and_ordering_two_completed():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_ticks(
        o,
        [{"cpu": 95.0}] * 5
        + [{"cpu": 11.0}] * 10
        + [{"memory": 94.0}] * 5
        + [{"memory": 20.0}] * 10,
    )
    recent = o.view_state().recent_episodes
    # Deterministic ordering and strictly increasing ids within a session.
    assert [e.episode_id for e in recent] == ["P-002", "P-001"]
    starts = [e.started_at for e in reversed(recent)]
    assert starts == sorted(starts)


def test_episode_ids_reset_after_session_reset():
    o = _orchestrator()
    o.begin_session("A", timestamp=0.0)
    _drive_ticks(o, [{"cpu": 95.0}] * 5 + [{"cpu": 10.0}] * 10)
    assert o.view_state().recent_episodes[0].episode_id == "P-001"
    o.end_session()
    o.begin_session("B", timestamp=100.0)
    _drive_ticks(o, [{"cpu": 95.0}] * 5)
    assert o.view_state().active_episodes[0].episode_id == "P-001"


def test_score_trajectory_recorded_on_completed_episode():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_ticks(o, [{"cpu": 96.0}] * 5 + [{"cpu": 10.0}] * 10)
    ep = o.view_state().recent_episodes[0]
    assert isinstance(ep.score_at_start, int)
    assert ep.score_min is not None
    assert ep.score_at_recovery is not None
    assert 0 <= ep.score_min <= 100
    assert ep.score_delta == ep.score_at_recovery - ep.score_at_start
    assert ep.score_at_recovery > ep.score_min  # device observed to recover


def test_steady_state_ticks_do_not_explode_evidence():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    _drive_ticks(o, [{"cpu": 95.0}] * 30)
    state = o.view_state()
    assert len(state.active_episodes) == 1
    ep = state.active_episodes[0]
    assert ep.episode_id == "P-001"
    assert len(ep.evidence) <= EVIDENCE_RETENTION


def test_completed_episode_retention_bound():
    t = EpisodeTracker()
    total = EPISODE_RETENTION + 5
    for i in range(total):
        cond = ActiveCondition(
            key="cpu:c",
            finding=_finding(sev="critical"),
            metric="cpu",
            first_seen=float(i),
            last_seen=float(i),
        )
        t.update(started=(cond,), recovered=(), now=float(i))
        t.update(started=(), recovered=(cond,), now=float(i) + 0.5)
    completed = t.completed_episodes
    assert len(completed) == EPISODE_RETENTION
    assert completed[-1].episode_id == f"P-{total:03d}"


def test_missing_values_stay_missing_not_zero():
    session = PerformanceSession()  # deliberately no samples recorded
    ep = build_grouped_episode(
        episode_id="P-001",
        condition_keys=("process:c",),
        metrics=("process",),
        severity="critical",
        first_seen=0.0,
        last_seen=4.0,
        is_active=False,
        current_time=None,
        session=session,
    )
    assert ep.peak_value is None
    assert ep.baseline_value is None
    assert ep.score_at_start is None
    assert ep.score_min is None
    assert ep.score_at_recovery is None
    assert ep.score_delta is None


# --------------------------------------------------------------------------
# Architecture / honesty audit
# --------------------------------------------------------------------------

def test_performance_layer_has_no_forbidden_capability():
    forbidden = (
        "QTimer",
        "MonitorWorker",
        "import subprocess",
        "import adb",
        "pm list packages",
        "backgroundworker",
    )
    for path in PERF_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token.lower() not in text, f"{path.name} contains {token!r}"


def test_no_pyside_import_in_performance():
    for path in PERF_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "PySide6" not in text, f"{path.name} imports PySide6"


def test_disconnect_clears_device_bound_state():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    o.ingest(cpu=_cpu_snap(30, 0.0), background_apps=_bg_hist(1)[0][1], timestamp=0.0)
    o.ingest(background_apps=_bg_hist(1)[0][1], timestamp=1.0)
    assert len(o._background_history) >= 1
    o.end_session()
    assert o._background_history == []
    assert o.episodes.open_record() is None
    assert o.episodes.completed_episodes == ()
    assert o.episodes.episode_count == 0
