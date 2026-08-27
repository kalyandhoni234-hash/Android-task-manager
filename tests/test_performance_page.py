"""Tests for the Performance Intelligence UI (Phase 3 presentation).

These verify the page + summary render the orchestrator's
:class:`PerformanceViewState` correctly and honestly:

* pressure shows in the overview badge and the metric card condition;
* evidence is grouped (observed / threshold / baseline / change / correlated)
  and never asserts a root cause;
* application rows are *correlation*, never "caused by";
* lifecycle STARTED / ACTIVE / RECOVERED render;
* disconnected / collecting / normal states are distinct and never fabricated;

No QTimer, no MonitorWorker, no real ADB — the UI is driven directly by
``view_state`` snapshots.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from android_task_manager.gui.intelligence_page import IntelligencePage  # noqa: E402
from android_task_manager.gui.performance_page import (  # noqa: E402
    PerformancePage,
    PerformanceSummaryWidget,
)
from android_task_manager.performance.baseline import Baseline  # noqa: E402
from android_task_manager.performance.models import EvidenceKind  # noqa: E402
from android_task_manager.performance.view import (  # noqa: E402
    STATE_CPU_PRESSURE,
    STATE_MEMORY_PRESSURE,
    STATE_MULTI_METRIC,
    STATE_NORMAL,
    AppCorrelation,
    EventRow,
    EvidenceRow,
    FindingView,
    MetricView,
    PerformanceViewState,
)


def qtapp():
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _metric(key: str, label: str, current, condition, baseline=None, delta=None,
            occupancy=None, evidence=None) -> MetricView:
    return MetricView(
        key=key, label=label, unit="%", current=current, baseline=baseline,
        delta=delta, occupancy=occupancy, condition=condition, evidence=evidence,
    )


def _baseline(median, p95, stddev, count=20) -> Baseline:
    return Baseline(
        metric="cpu", count=count, mean=median, median=median, p95=p95,
        minimum=median - 5.0, maximum=p95 + 5.0, stddev=stddev,
    )


def _finding(severity: str, title: str, phase: str = "active") -> FindingView:
    return FindingView(
        severity=severity, category="cpu", title=title, evidence="evidence",
        phase=phase, first_seen=1.0,
    )


def _evidence(group: str, statement: str, metric="cpu") -> EvidenceRow:
    return EvidenceRow(
        group=group, metric=metric, statement=statement,
        kind=EvidenceKind.STATISTIC,
    )


def _app(package: str, label=None, cpu=None, mem=None, procs=2, state="background") -> AppCorrelation:
    return AppCorrelation(
        package=package, label=label, cpu_percent=cpu, memory_percent=mem,
        process_count=procs, state=state,
    )


def _event(phase: str, title: str) -> EventRow:
    severity = {"started": "high", "active": "elevated", "recovered": "info"}.get(phase, "info")
    return EventRow(phase=phase, title=title, severity=severity, monotonic=1.0)


def _display(constant: str) -> str:
    return constant.replace("_", " ")


def _state(overall=STATE_NORMAL, metrics=None, findings=(), evidence=(),
           apps=(), events=(), history=None) -> PerformanceViewState:
    return PerformanceViewState(
        overall_state=overall,
        metrics=metrics or {},
        findings=tuple(findings),
        evidence=tuple(evidence),
        app_correlations=tuple(apps),
        events=tuple(events),
        history=history or {},
    )


def _reason(widget) -> str:
    label = widget.findChild(QLabel, "findingReason")
    return label.text() if label is not None else ""


def _card_titles(page: PerformancePage) -> list[str]:
    titles = []
    for i in range(page._findings_layout.count()):
        item = page._findings_layout.itemAt(i)
        if item is None or item.widget() is None:
            continue
        label = item.widget().findChild(QLabel, "findingRule")
        if label is not None:
            titles.append(label.text())
    return titles


# --------------------------------------------------------------------------
# A. Page creates cleanly (offscreen, no ADB module imported at runtime)
# --------------------------------------------------------------------------


def test_page_creates_without_application():
    qtapp()
    page = PerformancePage()
    assert page.objectName() == "performancePage"


# --------------------------------------------------------------------------
# B. Disconnected device: honest empty state, no fabricated cards
# --------------------------------------------------------------------------


def test_disconnected_shows_disconnected_state():
    qtapp()
    page = PerformancePage()
    page.refresh(_state(), connected=False)
    assert page._state.text() == "DEVICE DISCONNECTED"
    assert page._findings_layout.count() == 1
    empty = page._findings_layout.itemAt(0).widget()
    assert "No device connected" in empty.text()


# --------------------------------------------------------------------------
# C. Connected but no data: collecting states, not fabricated zeros
# --------------------------------------------------------------------------


def test_connected_collecting_shows_baseline_pending():
    qtapp()
    page = PerformancePage()
    page.refresh(_state(STATE_NORMAL), connected=True)
    assert page._state.text() == STATE_NORMAL
    assert "No active performance conditions" in page._findings_layout.itemAt(0).widget().text()
    assert "Collecting baseline" in page._cards["cpu"]._baseline.text()


# --------------------------------------------------------------------------
# D. Normal state badge
# --------------------------------------------------------------------------


def test_normal_state_badge():
    qtapp()
    page = PerformancePage()
    page.refresh(_state(STATE_NORMAL), connected=True)
    assert page._state.text() == _display(STATE_NORMAL)


# --------------------------------------------------------------------------
# E. CPU pressure: overview badge + card condition
# --------------------------------------------------------------------------


def test_cpu_pressure_renders():
    qtapp()
    page = PerformancePage()
    metrics = {"cpu": _metric("cpu", "CPU", 95.0, "CRITICAL", _baseline(40.0, 60.0, 5.0),
                             delta=55.0, occupancy=0.9, evidence="cpu 95%")}
    page.refresh(_state(STATE_CPU_PRESSURE, metrics=metrics), connected=True)
    assert page._state.text() == _display(STATE_CPU_PRESSURE)
    assert page._cards["cpu"]._condition.text() == "CRITICAL"


# --------------------------------------------------------------------------
# F. Memory pressure
# --------------------------------------------------------------------------


def test_memory_pressure_renders():
    qtapp()
    page = PerformancePage()
    metrics = {"memory": _metric("memory", "Memory", 92.0, "ELEVATED",
                                _baseline(60.0, 70.0, 3.0))}
    page.refresh(_state(STATE_MEMORY_PRESSURE, metrics=metrics), connected=True)
    assert page._state.text() == _display(STATE_MEMORY_PRESSURE)
    assert page._cards["memory"]._condition.text() == "ELEVATED"


# --------------------------------------------------------------------------
# G. Multi-metric -> MULTI_METRIC badge
# --------------------------------------------------------------------------


def test_multi_metric_badge():
    qtapp()
    page = PerformancePage()
    metrics = {
        "cpu": _metric("cpu", "CPU", 95.0, "CRITICAL", _baseline(40.0, 60.0, 5.0)),
        "memory": _metric("memory", "Memory", 92.0, "CRITICAL", _baseline(60.0, 70.0, 3.0)),
    }
    page.refresh(_state(STATE_MULTI_METRIC, metrics=metrics), connected=True)
    assert page._state.text() == _display(STATE_MULTI_METRIC)


# --------------------------------------------------------------------------
# H. Evidence panel groups (observed/threshold/baseline/change/correlated)
# --------------------------------------------------------------------------


def test_evidence_groups_rendered_once_per_id():
    qtapp()
    page = PerformancePage()
    rows = [
        _evidence("observed", "cpu observed 95%"),
        _evidence("threshold", "cpu >= 90 critical"),
        _evidence("baseline", "baseline median 40%"),
        _evidence("change", "cpu +55pp vs baseline"),
        _evidence("correlated", "app com.x active during window"),
    ]
    page.refresh(_state(evidence=rows), connected=True)
    group_titles = [
        page._evidence_layout.itemAt(i).widget().text()
        for i in range(page._evidence_layout.count())
        if page._evidence_layout.itemAt(i).widget() is not None
        and page._evidence_layout.itemAt(i).widget().objectName() == "evidenceGroupTitle"
    ]
    assert "OBSERVED" in group_titles
    assert "THRESHOLD" in group_titles
    assert "BASELINE" in group_titles
    assert "CHANGE" in group_titles
    assert "CORRELATED ACTIVITY" in group_titles
    # No duplicate: re-render the same ids -> still 5 data rows (not 10).
    page.refresh(_state(evidence=rows), connected=True)
    data_rows = [
        page._evidence_layout.itemAt(i).widget()
        for i in range(page._evidence_layout.count())
        if page._evidence_layout.itemAt(i).widget() is not None
        and page._evidence_layout.itemAt(i).widget().objectName() == "evidenceRow"
    ]
    assert len(data_rows) == 5


# --------------------------------------------------------------------------
# I. Baseline statistics + occupancy shown
# --------------------------------------------------------------------------


def test_baseline_stats_shown():
    qtapp()
    page = PerformancePage()
    metrics = {"cpu": _metric("cpu", "CPU", 95.0, "CRITICAL", _baseline(40.0, 60.0, 5.0),
                             delta=55.0, occupancy=0.9)}
    page.refresh(_state(metrics=metrics), connected=True)
    text = page._cards["cpu"]._baseline.text()
    assert "40.0%" in text and "60.0%" in text and "5.0%" in text
    assert "90%" in page._cards["cpu"]._occupancy.text()


# --------------------------------------------------------------------------
# J. Insufficient baseline -> collecting message
# --------------------------------------------------------------------------


def test_insufficient_baseline_shows_collecting():
    qtapp()
    page = PerformancePage()
    metrics = {"cpu": _metric("cpu", "CPU", 95.0, "CRITICAL", None, None, None)}
    page.refresh(_state(metrics=metrics), connected=True)
    assert "Collecting baseline" in page._cards["cpu"]._baseline.text()


# --------------------------------------------------------------------------
# K. Application correlation (correlation, never "caused by")
# --------------------------------------------------------------------------


def test_app_correlation_renders_and_no_causation():
    qtapp()
    page = PerformancePage()
    apps = [_app("com.example.heavy", label="Heavy App", cpu=30.0, mem=12.0, procs=3)]
    page.refresh(_state(apps=apps), connected=True)
    assert page._apps_layout.count() == 1
    text = page._apps_layout.itemAt(0).widget().findChild(QLabel, "findingRule").text()
    assert "Heavy App" in text or "com.example.heavy" in text
    full = page._apps_layout.itemAt(0).widget().findChild(QLabel, "diagField").text()
    assert "caused by" not in full.lower()


# --------------------------------------------------------------------------
# L. Package fallback when no label resolved
# --------------------------------------------------------------------------


def test_app_correlation_package_fallback():
    qtapp()
    page = PerformancePage()
    apps = [_app("com.example.nolabel", label=None, cpu=10.0, mem=5.0, procs=1)]
    page.refresh(_state(apps=apps), connected=True)
    name = page._apps_layout.itemAt(0).widget().findChild(QLabel, "findingRule").text()
    assert "com.example.nolabel" in name


# --------------------------------------------------------------------------
# M. Lifecycle events STARTED / ACTIVE / RECOVERED
# --------------------------------------------------------------------------


def test_lifecycle_events_render():
    qtapp()
    page = PerformancePage()
    events = [
        _event("started", "cpu pressure started"),
        _event("active", "cpu pressure escalated"),
        _event("recovered", "cpu pressure recovered"),
    ]
    page.refresh(_state(events=events), connected=True)
    assert page._events_layout.count() == 3
    first = _reason(page._events_layout.itemAt(0).widget())
    assert "started" in first


# --------------------------------------------------------------------------
# N. Reconnect clears stale prior disconnected rendering
# --------------------------------------------------------------------------


def test_reconnect_clears_stale_disconnected():
    qtapp()
    page = PerformancePage()
    page.refresh(_state(), connected=False)
    assert page._state.text() == "DEVICE DISCONNECTED"
    finding = _finding("CRITICAL", "CPU critical")
    page.refresh(_state(STATE_CPU_PRESSURE, findings=(finding,)), connected=True)
    assert page._state.text() == _display(STATE_CPU_PRESSURE)
    assert _card_titles(page) == ["CPU critical"]


# --------------------------------------------------------------------------
# O. No ADB / QTimer / MonitorWorker in the presentation layer
# --------------------------------------------------------------------------


def test_presentation_layer_has_no_adb_or_timers():
    import pathlib

    base = pathlib.Path(__file__).resolve().parents[1] / "src" / "android_task_manager"
    files = [
        base / "gui" / "performance_page.py",
        base / "gui" / "intelligence_page.py",
        base / "gui" / "performance_integration.py",
    ]
    forbidden = ("QTimer(", "MonitorWorker(", "subprocess.", "adb shell")
    for path in files:
        content = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in content, f"{path.name} must not contain {token!r}"


# --------------------------------------------------------------------------
# P. Intelligence page keeps its existing sections + new performance section
# --------------------------------------------------------------------------


def test_intelligence_page_has_performance_section():
    qtapp()
    page = IntelligencePage()
    assert hasattr(page, "_perf_summary")
    # Existing core sections still present (object names unchanged).
    assert page.findChild(QLabel, "intelligenceSection") is not None
    # Compact summary refreshes from the same view state.
    metrics = {"cpu": _metric("cpu", "CPU", 95.0, "CRITICAL", _baseline(40.0, 60.0, 5.0))}
    page.refresh_performance(_state(STATE_CPU_PRESSURE, metrics=metrics,
                                    findings=(_finding("CRITICAL", "CPU critical"),)),
                             connected=True)
    assert page._perf_summary._state.text() == _display(STATE_CPU_PRESSURE)
    assert "1 active condition" in page._perf_summary._findings.text()


def test_intelligence_summary_disconnected():
    qtapp()
    page = IntelligencePage()
    page.refresh_performance(_state(), connected=False)
    assert page._perf_summary._state.text() == "DISCONNECTED"


# --------------------------------------------------------------------------
# Q. Compact summary widget reflects state independently
# --------------------------------------------------------------------------


def test_summary_widget_renders():
    qtapp()
    widget = PerformanceSummaryWidget()
    metrics = {
        "cpu": _metric("cpu", "CPU", 95.0, "CRITICAL", _baseline(40.0, 60.0, 5.0)),
        "memory": _metric("memory", "Memory", 80.0, "ELEVATED", _baseline(60.0, 70.0, 3.0)),
        "storage": _metric("storage", "Storage", 70.0, "NORMAL", _baseline(60.0, 65.0, 2.0)),
        "battery": _metric("battery", "Battery", 50.0, "NORMAL", None),
    }
    widget.refresh(_state(STATE_CPU_PRESSURE, metrics=metrics), connected=True)
    assert "Cpu" in widget._metrics.text()
    assert "Memory" in widget._metrics.text()
