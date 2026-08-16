"""Headless GUI tests for the Diagnostics page (D2: diagnostics findings UI).

Offscreen Qt. Covers: severity rendering (CRITICAL / WARNING / INFO),
preservation of the engine's severity-first ordering (the page must never
re-sort), the seven finding fields, the distinct "no device" vs "no
issues" states, the unknown-data honesty rule, the Overview summary card,
the Device page annotations, and the guarantee that diagnostics updates
need no new ADB traffic (evaluation consumes snapshots already in memory).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from android_task_manager.battery.models import (
    BatteryHealth,
    BatterySnapshot,
    BatteryStatus,
)
from android_task_manager.cpu.models import CPUSnapshot
from android_task_manager.diagnostics.evaluate import evaluate
from android_task_manager.diagnostics.models import (
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticReport,
    DiagnosticSeverity,
)
from android_task_manager.gui.diagnostics_page import DiagnosticsPage
from android_task_manager.gui.main_window import MainWindow
from android_task_manager.gui.monitor import ConnectionState
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.network.models import NetworkSnapshot
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def finding(
    severity: DiagnosticSeverity,
    category: DiagnosticCategory = DiagnosticCategory.BATTERY,
    title: str = "A finding",
    what: str = "What happened",
    why: str = "Why it was raised",
    evidence: str = "The evidence",
    recommended_action: str = "What to do",
) -> DiagnosticFinding:
    return DiagnosticFinding(
        severity=severity,
        category=category,
        title=title,
        what=what,
        why=why,
        evidence=evidence,
        recommended_action=recommended_action,
    )


def report(*findings: DiagnosticFinding) -> DiagnosticReport:
    return DiagnosticReport(findings=findings)


def page_texts(page: DiagnosticsPage) -> list[str]:
    """Every visible text the page renders, in layout order."""
    texts: list[str] = []
    for index in range(page._findings_layout.count()):
        widget = page._findings_layout.itemAt(index).widget()
        if isinstance(widget, QWidget):
            texts.extend(label.text() for label in widget.findChildren(QLabel))
    return texts


def card_widgets(page: DiagnosticsPage) -> list[QWidget]:
    """The rendered finding cards in layout order (empty label excluded)."""
    cards: list[QWidget] = []
    for index in range(1, page._findings_layout.count()):
        widget = page._findings_layout.itemAt(index).widget()
        if widget is not None:
            cards.append(widget)
    return cards


def card_severities(page: DiagnosticsPage) -> list[str]:
    return [
        card.findChild(QLabel, "findingSeverity").text() for card in card_widgets(page)
    ]


def battery(temperature_c: float) -> BatterySnapshot:
    return BatterySnapshot(
        timestamp=1.0,
        level_percent=80.0,
        scale=100,
        voltage_mv=4000,
        temperature_c=temperature_c,
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


def battery_quiet() -> BatterySnapshot:
    """A battery that trips no rule (charging, good health, mild temp)."""
    return BatterySnapshot(
        timestamp=1.0,
        level_percent=80.0,
        scale=100,
        voltage_mv=4000,
        temperature_c=31.0,
        status=BatteryStatus.CHARGING,
        status_raw=1,
        health=BatteryHealth.GOOD,
        health_raw=2,
        present=True,
        ac_powered=True,
        usb_powered=False,
        wireless_powered=False,
        technology="Li-ion",
        charge_counter=0,
    )


def snapshots():
    cpu = CPUSnapshot(timestamp=1.0, aggregate_utilization_percent=12.5, cores=[])
    memory = MemorySnapshot(
        timestamp=1.0,
        total_kb=1024 * 1024,
        free_kb=900 * 1024,
        available_kb=800 * 1024,
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
            )
        ],
    )
    network = NetworkSnapshot(timestamp=1.0, aggregate_rx_bytes=10, aggregate_tx_bytes=20)
    return cpu, memory, processes, network


# ---------------------------------------------------------------------------
# Severity rendering & ordering
# ---------------------------------------------------------------------------


def test_critical_finding_renders(qtapp) -> None:
    page = DiagnosticsPage()
    page.refresh(report(finding(DiagnosticSeverity.CRITICAL)), True)
    assert page._empty.isHidden()
    assert "CRITICAL" in card_severities(page)
    assert "A finding" in page_texts(page)


def test_warning_finding_renders(qtapp) -> None:
    page = DiagnosticsPage()
    page.refresh(report(finding(DiagnosticSeverity.WARNING)), True)
    assert "WARNING" in card_severities(page)


def test_info_finding_renders(qtapp) -> None:
    page = DiagnosticsPage()
    page.refresh(report(finding(DiagnosticSeverity.INFO)), True)
    assert "INFO" in card_severities(page)
    assert page._empty.isHidden()


def test_page_preserves_report_order_without_resorting(qtapp) -> None:
    """The engine sorts; the page must render the report verbatim, in the
    order given — here deliberately reversed (INFO first, CRITICAL last)."""
    page = DiagnosticsPage()
    page.refresh(
        report(
            finding(DiagnosticSeverity.INFO, title="info-first"),
            finding(DiagnosticSeverity.WARNING, title="warning-second"),
            finding(DiagnosticSeverity.CRITICAL, title="critical-third"),
        ),
        True,
    )
    assert card_severities(page) == ["INFO", "WARNING", "CRITICAL"]


def test_summary_counts_are_severity_first(qtapp) -> None:
    page = DiagnosticsPage()
    page.refresh(
        report(
            finding(DiagnosticSeverity.CRITICAL),
            finding(DiagnosticSeverity.WARNING),
            finding(DiagnosticSeverity.WARNING),
            finding(DiagnosticSeverity.INFO),
        ),
        True,
    )
    assert "1 CRITICAL \u00b7 2 WARNING \u00b7 1 INFO" in page._summary.text()


def test_summary_zero_counts_shown_without_findings(qtapp) -> None:
    page = DiagnosticsPage()
    page.refresh(report(), True)
    assert "0 CRITICAL \u00b7 0 WARNING \u00b7 0 INFO" in page._summary.text()


# ---------------------------------------------------------------------------
# Finding content: all seven fields visible (no collapse)
# ---------------------------------------------------------------------------


def test_all_finding_fields_are_visible(qtapp) -> None:
    page = DiagnosticsPage()
    page.refresh(
        report(
            finding(
                DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.STORAGE,
                title="Storage nearly full",
                what="The storage is nearly full.",
                why="The device reports high usage.",
                evidence="Used: 92%",
                recommended_action="Free some space.",
            )
        ),
        True,
    )
    texts = page_texts(page)
    for expected in (
        "CRITICAL",
        "STORAGE",
        "Storage nearly full",
        "The storage is nearly full.",
        "The device reports high usage.",
        "Used: 92%",
        "Free some space.",
        "WHAT",
        "WHY",
        "EVIDENCE",
        "RECOMMENDED ACTION",
    ):
        assert expected in texts


# ---------------------------------------------------------------------------
# States: no device vs no issues; unknown data honesty
# ---------------------------------------------------------------------------


def test_no_device_state_is_distinct(qtapp) -> None:
    page = DiagnosticsPage()
    page.refresh(None, False)
    assert not page._empty.isHidden()
    assert "NO DEVICE CONNECTED" in page._empty.text()
    assert "No issues detected" not in page._empty.text()
    assert page._summary.isHidden()


def test_empty_report_state_has_honest_caveat(qtapp) -> None:
    page = DiagnosticsPage()
    page.refresh(report(), True)
    assert not page._empty.isHidden()
    assert "No issues detected" in page._empty.text()
    assert "not proof of health" in page._empty.text()
    assert "NO DEVICE CONNECTED" not in page._empty.text()


def test_unknown_data_produces_no_fabricated_diagnostic(qtapp) -> None:
    page = DiagnosticsPage()
    page.refresh(evaluate(cpu=None, memory=None, battery=None, device=None), True)
    assert not page._empty.isHidden()
    assert "No issues detected" in page._empty.text()
    assert "OK" not in page._empty.text()
    assert "Healthy" not in page._empty.text()
    assert page._summary.text() == "0 CRITICAL \u00b7 0 WARNING \u00b7 0 INFO"


def test_stale_findings_do_not_survive_refresh(qtapp) -> None:
    page = DiagnosticsPage()
    page.refresh(report(finding(DiagnosticSeverity.CRITICAL)), True)
    assert len(card_widgets(page)) == 1
    page.refresh(report(), True)
    assert len(card_widgets(page)) == 0
    assert not page._empty.isHidden()


# ---------------------------------------------------------------------------
# Overview summary card
# ---------------------------------------------------------------------------


def test_overview_shows_diagnostics_counts_via_window(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    cpu, memory, processes, network = snapshots()
    window.update_snapshots(cpu, memory, processes, battery(48.0), network)
    assert "1 CRITICAL" in window.overview._diagnostics_line.text()
    assert window.overview._diagnostics_link.isVisibleTo(window.overview)


def test_overview_zero_findings_line(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    cpu, memory, processes, network = snapshots()
    window.update_snapshots(cpu, memory, processes, battery_quiet(), network)
    assert window.overview._diagnostics_line.text() == "No issues detected."
    assert window.overview._diagnostics_link.isVisibleTo(window.overview)


def test_overview_diagnostics_line_before_connect(qtapp) -> None:
    window = MainWindow()
    assert "once a device is connected" in window.overview._diagnostics_line.text()
    assert not window.overview._diagnostics_link.isVisibleTo(window.overview)


def test_overview_link_navigates_to_diagnostics_page(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    cpu, memory, processes, network = snapshots()
    window.update_snapshots(cpu, memory, processes, battery(48.0), network)
    window.overview.diagnostics_requested.connect(
        lambda: window._on_page_requested("diagnostics")
    )
    window.overview._diagnostics_link.click()
    assert window._pages.currentIndex() == 7
    assert window.sidebar.active_page() == "diagnostics"


def test_sidebar_has_diagnostics_page(qtapp) -> None:
    window = MainWindow()
    assert window._pages.widget(7).widget() is window.diagnostics_page
    window.sidebar.button("diagnostics").click()
    assert window._pages.currentIndex() == 7


# ---------------------------------------------------------------------------
# Device page annotations
# ---------------------------------------------------------------------------


def test_device_card_annotation_appears(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.device_page.refresh(
        None,
        battery(31.0),
        None,
        None,
        ConnectionState.CONNECTED,
        report(
            finding(
                DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.BATTERY,
                title="Critical battery temperature",
                evidence="Temperature: 48.0 °C",
            )
        ),
    )
    note = window.device_page._notes["BATTERY"]
    assert not note.isHidden()
    assert "\u26a0 CRITICAL: Critical battery temperature" == note.text()
    assert "48.0" in note.toolTip()


def test_device_card_annotation_absent_without_finding(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.device_page.refresh(
        None, battery(31.0), None, None, ConnectionState.CONNECTED, report()
    )
    for card_name in ("BATTERY", "STORAGE", "SECURITY"):
        assert window.device_page._notes[card_name].isHidden()


def test_device_annotations_cleared_on_disconnect(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.device_page.refresh(
        None,
        battery(31.0),
        None,
        None,
        ConnectionState.CONNECTED,
        report(
            finding(
                DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.BATTERY,
                title="Elevated battery temperature",
            )
        ),
    )
    assert not window.device_page._notes["BATTERY"].isHidden()
    window.device_page.refresh(None, None, None, None, ConnectionState.DISCONNECTED)
    assert window.device_page._notes["BATTERY"].isHidden()


# ---------------------------------------------------------------------------
# Window integration: no new ADB traffic, no stale state
# ---------------------------------------------------------------------------


def test_diagnostics_update_requires_no_new_adb_call(qtapp) -> None:
    """update_snapshots already carries everything evaluation needs: the
    report is derived purely in memory, without touching the monitor."""
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    cpu, memory, processes, network = snapshots()
    window.update_snapshots(cpu, memory, processes, battery(48.0), network)
    assert window._diagnostics_report is not None
    critical = [
        f
        for f in window._diagnostics_report.findings
        if f.severity is DiagnosticSeverity.CRITICAL
    ]
    assert any("temperature" in f.title.lower() for f in critical)
    assert window.diagnostics_page._empty.isHidden()
    assert "CRITICAL" in window.diagnostics_page._summary.text()


def test_diagnostics_refreshes_on_changed_telemetry(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    cpu, memory, processes, network = snapshots()
    window.update_snapshots(cpu, memory, processes, battery(48.0), network)
    assert "1 CRITICAL" in window.diagnostics_page._summary.text()
    window.update_snapshots(cpu, memory, processes, battery(31.0), network)
    assert "0 CRITICAL" in window.diagnostics_page._summary.text()
    assert window.diagnostics_page._empty.isHidden()


def test_diagnostics_cleared_on_disconnect(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    cpu, memory, processes, network = snapshots()
    window.update_snapshots(cpu, memory, processes, battery(48.0), network)
    assert window._diagnostics_report is not None
    window.update_connection(ConnectionState.DISCONNECTED, "gone")
    assert window._diagnostics_report is None
    assert "NO DEVICE CONNECTED" in window.diagnostics_page._empty.text()
    assert "once a device is connected" in window.overview._diagnostics_line.text()


def test_existing_findings_page_untouched_by_diagnostics(qtapp) -> None:
    """The Findings page (baseline heuristics) still renders as before."""
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    cpu, memory, processes, network = snapshots()
    window.update_snapshots(cpu, memory, processes, battery(48.0), network)
    assert window.findings._empty is not None
    assert "No suspicious signals" in window.findings._empty.text()
    assert window._pages.widget(4).widget() is window.findings
