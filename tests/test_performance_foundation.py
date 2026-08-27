"""Tests for the v0.9.0 performance analysis foundation.

Deterministic, device-free, sleep-free. Verifies the domain models, window,
baseline, evidence, events, session and the pure analyzer, and asserts the
architectural invariants: no new polling/timer, no Qt/ADB in the analysis
layer, reuse of existing history/diagnostics primitives, and no fabrication
of metrics or causes.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest

from android_task_manager.diagnostics.models import DiagnosticFinding as DiagDiagnosticFinding
from android_task_manager.history.metrics import MetricHistory
from android_task_manager.performance import (
    BaselineCalculator,
    EvidenceKind,
    PerformanceAnalyzer,
    PerformanceEvent,
    PerformanceEventType,
    PerformanceEvidence,
    PerformanceSample,
    PerformanceSession,
    PerformanceWindow,
    to_timeline_event,
)
from android_task_manager.performance.analyzer import DiagnosticFinding
from android_task_manager.timeline.models import TimelineEvent

_PY = Path(__file__).resolve().parents[1] / "src" / "android_task_manager" / "performance"


def _window(metric: str, values: list[float], step: float = 1.0) -> PerformanceWindow:
    w = PerformanceWindow(max_samples=1000, metrics=[metric])
    ts = 0.0
    for v in values:
        w.add(PerformanceSample(timestamp=ts, metrics={metric: v}))
        ts += step
    return w


# ----------------------------------------------------------------------
# PerformanceSample
# ----------------------------------------------------------------------

def test_sample_available_metrics_sorted_and_absent_values_skipped():
    s = PerformanceSample(timestamp=1.0, metrics={"cpu": 50.0, "memory": 30.0})
    assert s.available_metrics() == ("cpu", "memory")
    assert s.get("cpu") == 50.0
    assert s.get("battery") is None


# ----------------------------------------------------------------------
# PerformanceWindow (reuse of MetricHistory)
# ----------------------------------------------------------------------

def test_window_reuses_metric_history():
    w = _window("cpu", [10.0, 20.0, 30.0])
    assert isinstance(w.metric_history("cpu"), MetricHistory)


def test_window_stats_and_trend():
    w = _window("cpu", [10.0, 20.0, 30.0, 40.0])
    assert w.average("cpu") == 25.0
    assert w.minimum("cpu") == 10.0
    assert w.maximum("cpu") == 40.0
    assert w.latest("cpu") == 40.0
    assert w.trend("cpu").value == "rising"


def test_window_threshold_occupancy_deterministic():
    w = _window("cpu", [10.0, 90.0, 95.0, 5.0])
    # 2 of 4 samples >= 80
    assert w.threshold_occupancy("cpu", 80.0) == pytest.approx(0.5)
    assert w.threshold_occupancy("cpu", 999.0) == 0.0


def test_window_sustained_threshold_and_duration():
    w = _window("cpu", [90.0, 90.1, 90.2, 90.3], step=10.0)
    since = w.sustained_threshold("cpu", 80.0, duration=25.0)
    assert since is not None
    assert since == pytest.approx(0.0)
    assert w.sustained_threshold("cpu", 80.0, duration=1000.0) is None


def test_window_peak_periods():
    w = _window("cpu", [10.0, 90.0, 95.0, 10.0, 90.0])
    periods = w.peak_periods("cpu", 80.0, min_samples=2)
    assert len(periods) == 1
    assert periods[0].sample_count == 2


def test_window_duration_and_change_from_baseline():
    w = _window("cpu", [10.0, 20.0, 30.0], step=5.0)
    assert w.duration() == pytest.approx(10.0)
    assert w.change_from_baseline("cpu", 20.0) == pytest.approx(0.0)
    assert w.change_from_baseline("cpu", 10.0) == pytest.approx(10.0)


def test_window_empty_is_honest():
    w = PerformanceWindow(metrics=["cpu"])
    assert w.is_empty
    assert w.average("cpu") is None
    assert w.threshold_occupancy("cpu", 80.0) == 0.0
    assert w.duration() is None


def test_window_is_bounded():
    w = PerformanceWindow(max_samples=3, metrics=["cpu"])
    for i in range(10):
        w.add(PerformanceSample(timestamp=float(i), metrics={"cpu": float(i)}))
    assert len(w) == 3
    assert w.values("cpu") == (7.0, 8.0, 9.0)


# ----------------------------------------------------------------------
# Baseline
# ----------------------------------------------------------------------

def test_baseline_from_values_median_p95_stddev():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    b = BaselineCalculator.from_values("cpu", vals)
    assert b.count == 5
    assert b.mean == 30.0
    assert b.median == 30.0
    assert b.minimum == 10.0
    assert b.maximum == 50.0
    assert b.p95 == 50.0
    assert b.stddev == pytest.approx(statistics.pstdev(vals))


def test_baseline_from_window_matches_window_average():
    w = _window("cpu", [10.0, 20.0, 30.0])
    b = BaselineCalculator.from_window("cpu", w)
    assert b.mean == w.average("cpu")
    assert b.minimum == w.minimum("cpu")


def test_baseline_deviation_and_zscore_and_rate():
    b = BaselineCalculator.from_values("cpu", [10.0, 20.0, 30.0, 40.0, 50.0])
    assert BaselineCalculator.deviation(40.0, b) == pytest.approx(10.0)
    assert BaselineCalculator.zscore(40.0, b) is not None
    roc = BaselineCalculator.rate_of_change([10.0, 10.0, 40.0])
    assert roc == pytest.approx(3.0)
    assert BaselineCalculator.rate_of_change([10.0]) is None


def test_baseline_rejects_empty():
    with pytest.raises(ValueError):
        BaselineCalculator.from_values("cpu", [])
    with pytest.raises(ValueError):
        BaselineCalculator.from_window("cpu", PerformanceWindow(metrics=["cpu"]))


# ----------------------------------------------------------------------
# Evidence (deterministic, no fabrication)
# ----------------------------------------------------------------------

def test_statistic_evidence_statement_has_numbers():
    ev = PerformanceEvidence(
        evidence_id="x", timestamp=0.0, kind=EvidenceKind.STATISTIC,
        statement="cpu averaged 20.0% (min 10.0%, max 30.0%, trend rising) over 3 samples",
        metric="cpu", value=20.0, sample_count=3,
    )
    assert "20.0" in ev.statement
    assert "rising" in ev.statement


def test_sustained_evidence_none_when_not_sustained():
    from android_task_manager.performance.evidence import (
        sustained_threshold_evidence,
    )
    w = _window("cpu", [90.0, 10.0, 90.0], step=10.0)
    assert sustained_threshold_evidence("id", 0.0, "cpu", w, 80.0, 25.0) is None


# ----------------------------------------------------------------------
# Events adapter
# ----------------------------------------------------------------------

def test_to_timeline_event_adapter():
    ev = PerformanceEvent(
        timestamp=12.3,
        event_type=PerformanceEventType.CPU_PRESSURE,
        severity="critical",
        title="CPU critical",
        description="cpu high",
        entity="cpu",
        evidence_ids=("EVID-cpu-occ-crit",),
        device_serial="ABC",
    )
    tl = to_timeline_event(ev, event_id="T-007", device_serial="ABC")
    assert isinstance(tl, TimelineEvent)
    assert tl.event_id == "T-007"
    assert tl.event_type == "METRIC_ALERT"
    assert tl.severity == "critical"
    assert tl.monotonic == 12.3
    assert tl.evidence_refs == ("EVID-cpu-occ-crit",)
    assert tl.entity == "cpu"


# ----------------------------------------------------------------------
# Session (reuse of SessionHistory + extended window)
# ----------------------------------------------------------------------

def test_session_records_canonical_and_extended():
    s = PerformanceSession()
    s.begin_session("SERIAL", timestamp=0.0)
    s.record(
        cpu_used_percent=50.0, memory_used_percent=40.0,
        battery_level_percent=80.0, storage_used_percent=60.0,
        process_count=300, timestamp=1.0,
    )
    s.record(
        cpu_used_percent=55.0, memory_used_percent=42.0,
        battery_level_percent=79.0, storage_used_percent=61.0,
        process_count=310, timestamp=2.0,
    )
    cpu_win = s.window_for("cpu")
    assert cpu_win.average("cpu") == pytest.approx(52.5)
    assert s.extended.average("process_count") == pytest.approx(305.0)
    assert s.device_serial == "SERIAL"


def test_session_reset_is_device_scoped():
    s = PerformanceSession()
    s.begin_session("A", timestamp=0.0)
    s.record(cpu_used_percent=90.0, memory_used_percent=10.0,
             battery_level_percent=10.0, storage_used_percent=10.0, timestamp=1.0)
    s.begin_session("B", timestamp=5.0)
    assert s.is_empty
    assert s.device_serial == "B"


# ----------------------------------------------------------------------
# Analyzer (pure, evidence-first)
# ----------------------------------------------------------------------

def test_analyzer_healthy_no_finding_but_evidence_present():
    w = _window("cpu", [10.0, 12.0, 11.0, 13.0])
    analysis = PerformanceAnalyzer().analyze_cpu(w)
    assert analysis.findings == ()
    assert len(analysis.evidence) == 3  # stat + two occupancy


def test_analyzer_cpu_warning_finding():
    # Between elevated (warn) and critical thresholds: warning, not critical.
    w = _window("cpu", [75.0, 76.0, 77.0, 78.0])
    analysis = PerformanceAnalyzer().analyze_cpu(w)
    assert len(analysis.findings) == 1
    f = analysis.findings[0]
    assert f.severity.value[1] == "warning"
    assert f.category.value == "cpu"
    assert "76.5" in f.evidence


def test_analyzer_cpu_critical_finding():
    w = _window("cpu", [95.0, 96.0, 97.0, 98.0])
    analysis = PerformanceAnalyzer().analyze_cpu(w)
    f = analysis.findings[0]
    assert f.severity.value[1] == "critical"


def test_analyzer_memory_and_storage_share_logic():
    a = PerformanceAnalyzer()
    mem = a.analyze_memory(_window("memory", [92.0, 93.0, 94.0, 95.0]))
    sto = a.analyze_storage(_window("storage", [92.0, 93.0, 94.0, 95.0]))
    assert mem.findings and sto.findings
    assert mem.findings[0].category.value == "memory"
    assert sto.findings[0].category.value == "storage"


def test_analyzer_process_pressure_thresholds():
    a = PerformanceAnalyzer()
    low = a.analyze_process_pressure(_window("process_count", [10.0, 20.0, 15.0, 18.0]))
    warn = a.analyze_process_pressure(_window("process_count", [300.0, 300.0, 300.0, 300.0]))
    crit = a.analyze_process_pressure(_window("process_count", [500.0, 500.0, 500.0, 500.0]))
    assert low.findings == ()
    assert warn.findings[0].severity.value[1] == "warning"
    assert crit.findings[0].severity.value[1] == "critical"
    assert crit.findings[0].category.value == "process"


def test_analyzer_application_pressure_consumes_resolved_identity():
    a = PerformanceAnalyzer()
    loads = [
        ("com.example.heavy", "Heavy App", 40.0, 20.0),
        ("com.example.light", "Light App", 5.0, 2.0),
        ("com.example.mid", "Mid App", 15.0, 10.0),
    ]
    analysis = a.analyze_application_pressure(loads, top_n=2)
    assert len(analysis.evidence) == 2
    assert analysis.findings[0].title == "Top application load"
    assert "Heavy App" in analysis.findings[0].evidence


def test_analyzer_baseline_delta_evidence_present():
    w = _window("cpu", [90.0, 92.0, 91.0])
    b = BaselineCalculator.from_values("cpu", [10.0, 11.0, 12.0])
    analysis = PerformanceAnalyzer().analyze_cpu(w, baseline=b)
    assert any(e.kind == EvidenceKind.DELTA for e in analysis.evidence)


def test_analyzer_finding_uses_shared_diagnostics_contract():
    w = _window("cpu", [95.0, 96.0, 97.0, 98.0])
    f = PerformanceAnalyzer().analyze_cpu(w).findings[0]
    assert type(f) is DiagDiagnosticFinding
    assert DiagnosticFinding is DiagDiagnosticFinding


# ----------------------------------------------------------------------
# No-fabrication invariant
# ----------------------------------------------------------------------

_SPECULATIVE = ("because", "leak", "root cause", "likely caused", "probably due")


def test_analyzer_never_fabricates_cause():
    a = PerformanceAnalyzer()
    samples = [
        _window("cpu", [95.0, 96.0, 97.0]),
        _window("memory", [92.0, 93.0, 94.0]),
        _window("process_count", [500.0, 500.0]),
    ]
    analyses = [
        a.analyze_cpu(samples[0]),
        a.analyze_memory(samples[1]),
        a.analyze_process_pressure(samples[2]),
    ]
    for analysis in analyses:
        for f in analysis.findings:
            blob = " ".join([f.what, f.why, f.evidence, f.recommended_action]).lower()
            for word in _SPECULATIVE:
                assert word not in blob, f"speculative wording {word!r} in {blob!r}"


# ----------------------------------------------------------------------
# Architectural safety: no Qt / no ADB / no timer in the analysis layer
# ----------------------------------------------------------------------

_FORBIDDEN = (
    "PySide",
    "QTimer",
    "MonitorWorker",
    "QWidget",
    "QtCore",
    "QtWidgets",
    "QtGui",
    "subprocess",
)


def test_performance_layer_has_no_gui_or_poll_imports():
    for path in _PY.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in _FORBIDDEN:
            assert token not in text, f"{token} found in {path.name}"
