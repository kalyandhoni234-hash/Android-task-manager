"""Headless GUI tests for the Device Intelligence page (v0.8, offscreen Qt).

Covers the new page (index 9, navigation, v0.7 indices untouched), health
rendering, recommendations + Apply flow through the safe automation path,
timeline transitions (meaningful flips only), rule alerts, automation task
bookkeeping and the disconnect-clears-everything invariant.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QPushButton

from android_task_manager.action.models import ActionResult
from android_task_manager.battery.models import (
    BatteryHealth,
    BatterySnapshot,
    BatteryStatus,
)
from android_task_manager.cpu.models import CPUSnapshot
from android_task_manager.gui.main_window import MainWindow
from android_task_manager.gui.monitor import ConnectionState
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.network.models import (
    NetworkInterfaceSnapshot,
    NetworkSnapshot,
)
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot
from android_task_manager.recommend import Recommendation
from android_task_manager.timeline import EVENT_DEVICE_CONNECTED, EVENT_SESSION_STARTED


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _cpu(percent: float | None) -> CPUSnapshot:
    return CPUSnapshot(timestamp=1.0, aggregate_utilization_percent=percent, cores=[])


def _memory(used_percent: float) -> MemorySnapshot:
    return MemorySnapshot(
        timestamp=1.0,
        total_kb=1_000_000,
        free_kb=0,
        available_kb=1_000_000 * (1 - used_percent / 100.0),
        buffers_kb=0,
        cached_kb=0,
        swap_cached_kb=0,
    )


def _battery(level: float) -> BatterySnapshot:
    return BatterySnapshot(
        timestamp=1.0,
        level_percent=level,
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


def _processes(cpu: float = 5.0, memory: float = 5.0) -> ProcessSnapshot:
    return ProcessSnapshot(
        timestamp=1.0,
        processes=[
            ProcessInfo(
                pid=8150,
                name="com.example.app",
                uid=10001,
                state="R",
                cpu_percent=cpu,
                memory_percent=memory,
                category=ProcessCategory.USER,
            )
        ],
    )


def _network() -> NetworkSnapshot:
    return NetworkSnapshot(
        timestamp=1.0,
        interfaces=[
            NetworkInterfaceSnapshot(
                name="wlan0",
                rx_bytes=0,
                tx_bytes=0,
                rx_packets=0,
                tx_packets=0,
                rx_errors=0,
                tx_errors=0,
                rx_drops=0,
                tx_drops=0,
            )
        ],
    )


def connect_window(window: MainWindow) -> None:
    """Drive the window into its connected state with live data."""
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.on_serial_ready("FAKE123")
    window.update_snapshots(
        _cpu(12.5), _memory(40.0), _processes(), _battery(80.0), _network()
    )


# ---------------------------------------------------------------------------
# Page registration & navigation (v0.7 indices untouched)
# ---------------------------------------------------------------------------


def test_intelligence_page_registered_at_index_9(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    assert window._pages.widget(9).widget() is window.intelligence
    window.sidebar.button("intelligence").click()
    assert window._pages.currentIndex() == 9
    assert window.sidebar.active_page() == "intelligence"


def test_v07_navigation_indices_unchanged(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    for key, index in {
        "overview": 0,
        "processes": 1,
        "network": 2,
        "applications": 3,
        "baseline": 4,
        "findings": 5,
        "device": 6,
        "health": 7,
        "diagnostics": 8,
    }.items():
        window.sidebar.button(key).click()
        assert window._pages.currentIndex() == index, key


# ---------------------------------------------------------------------------
# Session lifecycle on the timeline
# ---------------------------------------------------------------------------


def test_session_started_recorded_on_serial(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.on_serial_ready("FAKE123")
    events = window._timeline.events
    assert events[0].event_type == EVENT_SESSION_STARTED
    assert events[0].device_serial == "FAKE123"
    assert events[0].event_id == "T-001"


def test_connection_transition_recorded_once(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    connected = window._timeline.of_type(EVENT_DEVICE_CONNECTED)
    assert len(connected) == 1  # meaningful transitions only


def test_disconnect_records_transition_and_clears_health(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    assert window._health is not None
    window.update_connection(ConnectionState.DISCONNECTED, "gone")
    assert window._health is None
    assert window.intelligence._health_status.text() == "\u2014 No device connected"
    disconnected = window._timeline.of_type("DEVICE_DISCONNECTED")
    assert len(disconnected) == 1


# ---------------------------------------------------------------------------
# Health rendering
# ---------------------------------------------------------------------------


def test_health_rendered_after_connect(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    assert window._health is not None
    assert "HEALTHY" in window.intelligence._health_status.text()
    assert "cpu: healthy" in window.intelligence._health_components.text()


def test_health_renders_warning_when_cpu_high(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.on_serial_ready("FAKE123")
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(cpu=90.0), _battery(80.0), _network()
    )
    assert window._health is not None
    assert window._health.status.value == "critical"
    assert "critical" in window.intelligence._health_status.text().lower()


# ---------------------------------------------------------------------------
# Rules and recommendations
# ---------------------------------------------------------------------------


def test_rule_fire_recorded_on_timeline(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.on_serial_ready("FAKE123")
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(cpu=90.0), _battery(80.0), _network()
    )
    assert len(window._rule_fires) >= 1
    assert any(event.event_type == "RULE_FIRED" for event in window._timeline.events)
    assert "CPU utilization is high" in window.intelligence._rules_label.text()


def test_recommendations_rendered_with_apply(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.on_serial_ready("FAKE123")
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(cpu=90.0), _battery(80.0), _network()
    )
    assert window._recommendations
    applies = window.intelligence.findChildren(QPushButton, "recommendationApply")
    assert len(applies) >= 1


def test_apply_click_emits_signal(qtapp, monkeypatch) -> None:
    window = MainWindow()
    connect_window(window)
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(cpu=90.0), _battery(80.0), _network()
    )
    monkeypatch.setattr(window, "_confirm_apps_action", lambda *args: True)
    recorded: list = []
    window.intelligence.apply_requested.connect(lambda rec: recorded.append(rec))
    apply = window.intelligence.findChildren(QPushButton, "recommendationApply")[0]
    apply.click()
    assert len(recorded) == 1
    assert recorded[0].action == "force_stop"
    assert recorded[0].target == "com.example.app"


# ---------------------------------------------------------------------------
# Automation Apply flow (through the safe path)
# ---------------------------------------------------------------------------


def _automation_ready_recommendation() -> Recommendation:
    """A recommendation the automation path accepts (never destructive)."""
    return Recommendation(
        recommendation_id="REC-001",
        finding_ref="finding",
        title="Enable idle app",
        rationale="The recommendation engine proposed it.",
        severity="warning",
        action="enable",
        target="com.example.app",
        destructive=False,
        automation_allowed=True,
    )


def _wire_automation(window: MainWindow, monkeypatch) -> None:
    """Mirror the production wiring (app.wire_actions): the engine's gate
    requires an executor; the GUI flow only needs it configured, the real
    result arrives through on_action_result."""
    window._automation.set_executor(
        lambda action, target: ActionResult(action, target, True, "dispatched")
    )
    emitted: list[tuple[str, str]] = []
    window.action_requested.connect(lambda a, p: emitted.append((a, p)))
    monkeypatch.setattr(
        "android_task_manager.gui.main_window.QMessageBox.information",
        lambda *args, **kwargs: None,
    )
    return emitted


def test_destructive_apply_uses_user_path_with_confirmation(qtapp, monkeypatch) -> None:
    window = MainWindow()
    connect_window(window)
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(cpu=90.0), _battery(80.0), _network()
    )
    confirmed: list[bool] = [False]
    monkeypatch.setattr(window, "_confirm_apps_action", lambda *args: confirmed[0])
    emitted: list[tuple[str, str]] = []
    window.action_requested.connect(lambda a, p: emitted.append((a, p)))
    apply = window.intelligence.findChildren(QPushButton, "recommendationApply")[0]
    apply.click()
    assert emitted == []  # refused without confirmation
    assert window._pending_automation_task is None  # never an automation task
    confirmed[0] = True
    apply.click()
    assert emitted == [("force_stop", "com.example.app")]


def test_automation_path_runs_approved_action(qtapp, monkeypatch) -> None:
    window = MainWindow()
    connect_window(window)
    emitted = _wire_automation(window, monkeypatch)
    window._recommendations = (_automation_ready_recommendation(),)
    window._refresh_intelligence()
    apply = window.intelligence.findChildren(QPushButton, "recommendationApply")[0]
    apply.click()
    assert emitted == [("enable", "com.example.app")]
    assert window._pending_automation_task is not None
    # The action worker reports the typed result back.
    window.on_action_result(
        ActionResult(
            action="enable",
            package_name="com.example.app",
            success=True,
            message="Enabled com.example.app",
        )
    )
    tasks = window._automation.tasks
    assert tasks[-1].status.value == "succeeded"
    assert any(event.event_type == "ACTION_EXECUTED" for event in window._timeline.events)
    assert window._pending_automation_task is None


def test_automation_path_blocked_when_cooldown_active(qtapp, monkeypatch) -> None:
    window = MainWindow()
    connect_window(window)
    emitted = _wire_automation(window, monkeypatch)
    infos: list[str] = []
    monkeypatch.setattr(
        "android_task_manager.gui.main_window.QMessageBox.information",
        lambda *args, **kwargs: infos.append(str(args[-1])),
    )
    window._recommendations = (_automation_ready_recommendation(),)
    window._refresh_intelligence()
    apply = window.intelligence.findChildren(QPushButton, "recommendationApply")[0]
    # First run succeeds.
    apply.click()
    window.on_action_result(
        ActionResult(
            action="enable",
            package_name="com.example.app",
            success=True,
            message="ok",
        )
    )
    # Second run within the cooldown is blocked with a reason.
    apply.click()
    assert len(emitted) == 1
    assert infos and "Cooldown" in infos[-1]


def test_automation_tasks_rendered(qtapp, monkeypatch) -> None:
    window = MainWindow()
    connect_window(window)
    _wire_automation(window, monkeypatch)
    window._recommendations = (_automation_ready_recommendation(),)
    window._refresh_intelligence()
    apply = window.intelligence.findChildren(QPushButton, "recommendationApply")[0]
    apply.click()
    assert "A-001" in window.intelligence._automation_label.text()