"""Headless GUI tests for the Phase-A navigation shell (offscreen Qt).

Covers the persistent sidebar (structure, exclusive active state, page
switching), the connection strip, the Overview page (empty state, metrics,
security status derivation, activity facts), the Findings page (severity-
first cards, why wiring, hosted incident panel), and the guarantee that
every pre-existing panel widget survives the restructure intact.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QWidget

from android_task_manager.baseline import BaselineSnapshot, ProcessRef, diff_snapshot
from android_task_manager.battery.models import (
    BatteryHealth,
    BatterySnapshot,
    BatteryStatus,
)
from android_task_manager.cpu.models import CPUSnapshot
from android_task_manager.gui.connection_strip import ConnectionStrip
from android_task_manager.gui.main_window import MainWindow
from android_task_manager.gui.monitor import ConnectionState
from android_task_manager.gui.overview_page import OverviewPage, OverviewState
from android_task_manager.gui.sidebar import DEFAULT_PAGE, SECTIONS, Sidebar
from android_task_manager.heuristics import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    HeuristicReport,
    SuspiciousSignal,
    evaluate_heuristics,
)
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.network.models import NetworkSnapshot
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot

_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _proc(name: str, uid: int) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=ProcessCategory.USER)


def baseline_snapshot() -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=_AT,
        device_serial="TEST123",
        processes=frozenset({_proc("com.kept.app", 10002)}),
        packages=frozenset(),
        sockets=frozenset(),
    )


def current_snapshot() -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=_AT,
        device_serial="TEST123",
        processes=frozenset(
            {_proc("com.kept.app", 10002), _proc("com.new.app", 10003)}
        ),
        packages=frozenset(),
        sockets=frozenset(),
    )


def drift_check():
    """A stubbed worker result: (report, current, heuristics)."""
    baseline = baseline_snapshot()
    current = current_snapshot()
    report = diff_snapshot(baseline, current)
    return report, current, evaluate_heuristics(report, baseline, current)


def _report_with(*signals: SuspiciousSignal, rules: tuple[str, ...] = ()) -> HeuristicReport:
    return HeuristicReport(evaluated_at=_AT, signals=tuple(signals), rules_applied=rules)


def _signal(rule: str, severity: str, entity: str = "com.example.app") -> SuspiciousSignal:
    return SuspiciousSignal(
        rule_id=rule, severity=severity, entity=entity, reason=f"{rule} fired on {entity}"
    )


def snapshots() -> tuple[CPUSnapshot, MemorySnapshot, ProcessSnapshot, BatterySnapshot, NetworkSnapshot]:
    cpu = CPUSnapshot(timestamp=1.0, aggregate_utilization_percent=12.5, cores=[])
    memory = MemorySnapshot(
        timestamp=1.0,
        total_kb=1024 * 1024,
        free_kb=100 * 1024,
        available_kb=200 * 1024,
        buffers_kb=0,
        cached_kb=0,
        swap_cached_kb=0,
    )
    processes = ProcessSnapshot(
        timestamp=1.0,
        processes=[
            ProcessInfo(
                pid=1002,
                name="com.kept.app",
                uid=10002,
                state="S",
                cpu_percent=1.0,
                memory_percent=2.0,
                category=ProcessCategory.USER,
            ),
            ProcessInfo(
                pid=1003,
                name="com.new.app",
                uid=10003,
                state="S",
                cpu_percent=0.5,
                memory_percent=1.0,
                category=ProcessCategory.USER,
            ),
        ],
    )
    battery = BatterySnapshot(
        timestamp=1.0,
        level_percent=80.0,
        scale=100,
        voltage_mv=4000,
        temperature_c=31.0,
        status=BatteryStatus.DISCHARGING,
        status_raw=2,
        health=BatteryHealth.GOOD,
        health_raw=2,
        present=True,
        ac_powered=False,
        usb_powered=False,
        wireless_powered=False,
        technology="Li-ion",
        charge_counter=0,
    )
    network = NetworkSnapshot(timestamp=1.0, aggregate_rx_bytes=10, aggregate_tx_bytes=20)
    return cpu, memory, processes, battery, network


def connect_window(window: MainWindow) -> None:
    """Drive the window into its connected shell state with live data."""
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.update_device("vivo V2026", "11")
    cpu, memory, processes, battery, network = snapshots()
    window.update_snapshots(cpu, memory, processes, battery, network)


# ---------------------------------------------------------------------------
# Sidebar structure & navigation
# ---------------------------------------------------------------------------


def test_sidebar_sections_and_buttons(qtapp) -> None:
    sidebar = Sidebar()
    labels = {b.text() for b in sidebar.findChildren(QPushButton)}
    expected = {text for _section, items in SECTIONS for _key, text in items}
    assert expected <= labels
    assert sidebar.button("overview").isCheckable()
    assert not sidebar.button("overview").isChecked()  # nothing active yet


def test_sidebar_exclusive_active_state(qtapp) -> None:
    sidebar = Sidebar()
    sidebar.set_active("processes")
    assert sidebar.active_page() == "processes"
    assert sidebar.button("processes").isChecked()
    assert not sidebar.button("overview").isChecked()
    sidebar.set_active("overview")
    assert sidebar.active_page() == "overview"
    assert not sidebar.button("processes").isChecked()


def test_window_defaults_to_overview(qtapp) -> None:
    window = MainWindow()
    assert window._stack.currentIndex() == 0  # setup first
    assert window.sidebar.active_page() == DEFAULT_PAGE
    assert window._pages.currentIndex() == 0
    assert window._pages.currentWidget() is window.overview


def test_navigation_switches_pages(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    expectations = {
        "overview": 0,
        "processes": 1,
        "network": 2,
        "baseline": 3,
        "findings": 4,
        "device": 5,
        "health": 6,
    }
    for key, index in expectations.items():
        window.sidebar.button(key).click()
        assert window._pages.currentIndex() == index, key
        assert window.sidebar.active_page() == key, key


def test_navigation_preserves_widget_instances(qtapp) -> None:
    """Pages are created once and reused: the ProcessWidget instance inside
    the PROCESSES page is the very widget MainWindow reports."""
    window = MainWindow()
    connect_window(window)
    scroll = window._pages.widget(1)
    assert isinstance(scroll, QScrollArea)
    assert scroll.widget() is window.processes
    window.sidebar.button("device").click()
    window.sidebar.button("processes").click()
    assert window._pages.widget(1).widget() is window.processes


def test_unknown_page_request_is_ignored(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window.sidebar.button("health").click()
    window._on_page_requested("nonsense")
    assert window._pages.currentIndex() == 6
    assert window.sidebar.active_page() == "health"


# ---------------------------------------------------------------------------
# Connection strip
# ---------------------------------------------------------------------------


def test_connection_strip_reflects_state(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    assert window.connection_strip._status.text() == "\u25cf Connected"
    window.update_device("vivo V2026", "11")
    assert "vivo V2026" in window.connection_strip._device.text()
    assert "Android 11" in window.connection_strip._device.text()
    window.update_connection(ConnectionState.DISCONNECTED, "gone")
    assert "\u25cb" in window.connection_strip._status.text()


def test_connection_strip_states(qtapp) -> None:
    strip = ConnectionStrip()
    for state in (ConnectionState.ADB_MISSING, ConnectionState.OFFLINE):
        strip.set_state(state, "detail")
        assert strip._status.text()  # honest state text, never empty


# ---------------------------------------------------------------------------
# Overview page
# ---------------------------------------------------------------------------


def test_overview_empty_state(qtapp) -> None:
    window = MainWindow()
    for key in ("processes", "sockets", "drift", "high", "medium"):
        assert window.overview._cards[key].text() == "\u2014"
    assert "No findings" in window.overview._security_line.text()
    assert "No monitoring activity" in window.overview._activity.text()
    assert "No device selected" in window.overview._device_title.text()


def test_overview_after_connect_and_snapshots(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    assert window.overview._device_title.text() == "vivo V2026"
    assert window.overview._cards["processes"].text() == "2"
    assert window.overview._device_status.text() == "\u25cf Connected"
    assert "1 permission audit" not in window.overview._activity.text()


def test_overview_permission_audits_fact(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window._permission_audits.append("audit-1")
    window._permission_audits.append("audit-2")
    window._refresh_overview()
    assert "2 permission audits" in window.overview._activity.text()


def test_overview_security_status_high(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    report = _report_with(
        _signal("tampering", SEVERITY_HIGH),
        _signal("persistence", SEVERITY_MEDIUM),
        rules=("tampering", "persistence", "exfiltration"),
    )
    window._heuristics = report
    window._refresh_overview()
    assert window.overview._cards["high"].text() == "1"
    assert window.overview._cards["medium"].text() == "1"
    assert window.overview._cards["drift"].text() == "\u2014"
    assert "HIGH" in window.overview._security_line.text()
    assert "3 rule(s) applied" in window.overview._activity.text()


def test_overview_security_status_medium_only(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window._heuristics = _report_with(_signal("persistence", SEVERITY_MEDIUM))
    window._refresh_overview()
    assert window.overview._cards["high"].text() == "0"
    assert "MEDIUM" in window.overview._security_line.text()
    assert "HIGH or MEDIUM" not in window.overview._security_line.text()


def test_overview_security_status_no_signals(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window._heuristics = _report_with(rules=("tampering",))
    window._refresh_overview()
    assert "No HIGH or MEDIUM findings." == window.overview._security_line.text()


def test_overview_render_is_stable(qtapp) -> None:
    """Rendering with an all-None state never crashes and stays honest."""
    page = OverviewPage()
    page.refresh(OverviewState())
    assert page._cards["processes"].text() == "\u2014"
    assert "No findings to report yet." == page._security_line.text()


def test_overview_drift_link_shown_only_in_empty_state(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    assert window.overview._drift_link.isVisibleTo(window.overview)
    window._heuristics = _report_with(_signal("tampering", SEVERITY_HIGH))
    window._refresh_overview()
    assert not window.overview._drift_link.isVisibleTo(window.overview)
    window._heuristics = _report_with(rules=("tampering",))
    window._refresh_overview()
    assert not window.overview._drift_link.isVisibleTo(window.overview)


def test_overview_drift_link_navigates_to_baseline(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window.overview.baseline_requested.connect(
        lambda: window._on_page_requested("baseline")
    )
    window.overview._drift_link.click()
    assert window._pages.currentIndex() == 3
    assert window.sidebar.active_page() == "baseline"


# ---------------------------------------------------------------------------
# Findings page
# ---------------------------------------------------------------------------


def test_findings_empty_state_before_baseline(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    assert not window.findings._empty.isHidden()
    assert "No suspicious signals" in window.findings._empty.text()
    assert "baseline" in window.findings._empty.text().lower()


def test_findings_empty_state_no_signals(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window.findings.show_heuristics(_report_with(rules=("tampering",)))
    assert not window.findings._empty.isHidden()
    assert "1" in window.findings._empty.text()


def test_findings_renders_severity_first(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    report = _report_with(
        _signal("medium-rule", SEVERITY_MEDIUM),
        _signal("high-rule", SEVERITY_HIGH),
        _signal("info-rule", "INFO"),
    )
    window.findings.show_heuristics(report)
    assert window.findings._empty.isHidden()
    cards = [
        w
        for w in window.findings.findChildren(QWidget)
        if w.objectName().startswith("findingCard")
    ]
    # every signal gets a card, and HIGH is rendered first
    assert len(cards) == 3
    assert cards[0].objectName() == "findingCardHigh"
    texts = [c.findChild(QLabel, "findingRule").text() for c in cards]
    assert texts[0] == "high-rule"
    assert set(texts) == {"medium-rule", "high-rule", "info-rule"}


def test_findings_why_button_emits(qtapp, monkeypatch) -> None:
    window = MainWindow()
    connect_window(window)
    report = _report_with(_signal("high-rule", SEVERITY_HIGH))
    window.findings.show_heuristics(report)
    recorded: list = []
    window.findings.why_requested.connect(lambda s: recorded.append(s))
    card = window.findings.findChild(QWidget, "findingCardHigh")
    button = card.findChildren(QPushButton)[0]
    button.click()
    assert len(recorded) == 1
    assert recorded[0].rule_id == "high-rule"


def test_findings_why_click_opens_window_dialog(qtapp) -> None:
    """End-to-end: findings Why? runs the window's explain handler."""
    window = MainWindow()
    connect_window(window)
    baseline = baseline_snapshot()
    report, current, _heuristics = drift_check()
    window.on_baseline_saved(baseline)
    window.on_drift_checked(
        report,
        current,
        _report_with(_signal("high-rule", SEVERITY_HIGH), rules=("high-rule",)),
    )
    assert window._why_dialog is None
    card = window.findings.findChild(QWidget, "findingCardHigh")
    why = card.findChildren(QPushButton)[0]
    why.click()
    assert window._why_dialog is not None
    assert not window._why_dialog.isHidden()
    assert "high-rule" in window._why_dialog._view.toPlainText()
    window.close()


def test_findings_hosts_incident_panel(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    assert window.incident is not None
    assert window.incident.parent() is not None
    assert window._pages.widget(4).widget() is window.findings
    # the hosted panel still answers generation availability
    window.incident.set_generation_available(True)
    assert window.incident._generation_available is True


# ---------------------------------------------------------------------------
# Existing panels survive the restructure
# ---------------------------------------------------------------------------


def test_device_panel_on_device_page(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window.sidebar.button("device").click()
    scroll = window._pages.widget(5)
    assert scroll.widget() is window.device_page
    assert window.device_page._device is window.device
    assert window.device._status.text() == "\u25cf Connected"


def test_health_page_hosts_cpu_memory_battery(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    page = window._pages.widget(6).widget()
    children = {child for child in page.findChildren(QWidget)}
    assert window.cpu in children
    assert window.memory in children
    assert window.battery in children


def test_baseline_panel_buttons_survive(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window.sidebar.button("baseline").click()
    assert window.security._check_btn is not None
    assert window.security._save_btn is not None


def test_processes_table_renders_after_snapshots(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window.sidebar.button("processes").click()
    assert window.processes._table.rowCount() == 2


def test_update_banner_in_shell_and_dismissible(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    banner = window.update_banner
    assert banner.parent() is not None
    assert banner.parent() is not window.setup
    banner.show_result(_FakeUpdate(update_available=False))
    assert banner.isHidden()
    banner.show_result(_FakeUpdate(update_available=True))
    assert not banner.isHidden()
    banner._dismiss.click()
    assert banner.isHidden()


class _FakeUpdate:
    """Minimal UpdateCheckResult stand-in."""

    def __init__(self, update_available: bool) -> None:
        self.update_available = update_available
        self.latest_version = "9.9.9" if update_available else None
        self.release_url = (
            "https://example.invalid/releases/tag/v9.9.9" if update_available else None
        )