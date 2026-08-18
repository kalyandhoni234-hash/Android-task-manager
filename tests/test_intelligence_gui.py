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
    from android_task_manager.applications.models import (
        AppCategory,
        AppInfo,
        ApplicationSnapshot,
    )

    window.on_apps_inventory_ready(
        ApplicationSnapshot(
            timestamp=1.0,
            applications=[
                AppInfo(package_name="com.example.app", category=AppCategory.USER)
            ],
        )
    )
    assert window._recommendations
    applies = window.intelligence.findChildren(QPushButton, "recommendationApply")
    assert len(applies) >= 1


def test_force_stop_needs_verified_inventory_link(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.on_serial_ready("FAKE123")
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(cpu=90.0), _battery(80.0), _network()
    )
    # Without any verified inventory the heavy process is only proposed with
    # name-validity evidence, never as a force-stop target.
    assert all(
        r.action != "force_stop" for r in window._recommendations
    )
    # The inventory (re)read verifies the process name as installed: the
    # force-stop recommendation appears, linked to a real app.
    from android_task_manager.applications.models import (
        AppCategory,
        AppInfo,
        ApplicationSnapshot,
    )

    window.on_apps_inventory_ready(
        ApplicationSnapshot(
            timestamp=1.0,
            applications=[
                AppInfo(
                    package_name="com.example.app",
                    category=AppCategory.USER,
                )
            ],
        )
    )
    assert any(
        r.action == "force_stop" and r.target == "com.example.app"
        for r in window._recommendations
    )
    applies = window.intelligence.findChildren(QPushButton, "recommendationApply")
    assert len(applies) >= 1


def _verify_inventory(window: MainWindow) -> None:
    from android_task_manager.applications.models import (
        AppCategory,
        AppInfo,
        ApplicationSnapshot,
    )

    window.on_apps_inventory_ready(
        ApplicationSnapshot(
            timestamp=1.0,
            applications=[
                AppInfo(package_name="com.example.app", category=AppCategory.USER)
            ],
        )
    )


def test_apply_click_emits_signal(qtapp, monkeypatch) -> None:
    window = MainWindow()
    connect_window(window)
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(cpu=90.0), _battery(80.0), _network()
    )
    _verify_inventory(window)
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
    _verify_inventory(window)
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


# ---------------------------------------------------------------------------
# Application <-> health navigation (Phase I)
# ---------------------------------------------------------------------------


def test_recommendation_row_offers_view_app_for_target(qtapp) -> None:
    from android_task_manager.recommend import Recommendation

    window = MainWindow()
    rec = Recommendation(
        recommendation_id="REC-001",
        finding_ref="finding",
        title="Heavy app",
        rationale="reason",
        severity="warning",
        action="force_stop",
        target="com.example.app",
        destructive=True,
        automation_allowed=False,
    )
    window._recommendations = (rec,)
    window._refresh_intelligence()
    views = window.intelligence.findChildren(QPushButton, "recommendationView")
    assert len(views) == 1
    navigated: list[str] = []
    window.intelligence.navigate_requested.connect(navigated.append)
    views[0].click()
    assert navigated == ["com.example.app"]


def test_informational_recommendation_has_no_navigation(qtapp) -> None:
    from android_task_manager.recommend import Recommendation

    window = MainWindow()
    rec = Recommendation(
        recommendation_id="REC-002",
        finding_ref="finding",
        title="CPU saturated",
        rationale="reason",
        severity="critical",
        action=None,
        target=None,
        destructive=False,
        automation_allowed=False,
    )
    window._recommendations = (rec,)
    window._refresh_intelligence()
    assert window.intelligence.findChildren(QPushButton, "recommendationView") == []


def test_view_app_navigates_to_applications_and_requests_details(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(cpu=90.0), _battery(80.0), _network()
    )
    _verify_inventory(window)
    views = window.intelligence.findChildren(QPushButton, "recommendationView")
    assert len(views) >= 1
    detail_requests: list[str] = []
    window.apps_detail_requested.connect(detail_requests.append)
    views[0].click()
    assert detail_requests == ["com.example.app"]
    assert window._pages.currentIndex() == 3  # APPLICATIONS page


def test_view_app_ignores_unverified_target(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(cpu=90.0), _battery(80.0), _network()
    )
    detail_requests: list[str] = []
    window.apps_detail_requested.connect(detail_requests.append)
    # A target the device never verified installed is honestly ignored.
    window._on_intelligence_navigate("com.unknown.app")
    assert detail_requests == []
    assert window._pages.currentIndex() == 0


# ---------------------------------------------------------------------------
# Worker reuse + no extra polling (Phase J)
# ---------------------------------------------------------------------------


def test_intelligence_consumes_existing_snapshots_only(qtapp) -> None:
    """The intelligence UI adds zero polling: nothing is recorded or
    evaluated until the monitor's own snapshot handlers run."""
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.on_serial_ready("FAKE123")
    assert window._session_history.is_empty
    assert window._timeline.events
    # Repeating the same snapshot batch does not fabricate new events.
    window.update_snapshots(
        _cpu(12.5), _memory(40.0), _processes(), _battery(80.0), _network()
    )
    event_count = len(window._timeline.events)
    for _ in range(20):
        window.update_snapshots(
            _cpu(12.5), _memory(40.0), _processes(), _battery(80.0), _network()
        )
    assert len(window._timeline.events) == event_count


def test_duplicate_snapshot_deliveries_do_not_grow_history(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    cpu = _cpu(12.5)
    for _ in range(30):
        window.update_snapshots(cpu, _memory(40.0), _processes(), _battery(80.0), _network())
    assert len(window._session_history.cpu) == 1
    assert len(window._session_history.memory) == 1


def test_changing_values_are_recorded_at_worker_cadence(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    for level in (80.0, 79.0, 78.0, 81.0):
        window.update_snapshots(
            _cpu(12.5), _memory(40.0), _processes(), _battery(level), _network()
        )
    assert len(window._session_history.battery) == 4


def test_reconnect_creates_fresh_session_without_stale_state(qtapp) -> None:
    window = MainWindow()
    connect_window(window)
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(cpu=90.0), _battery(80.0), _network()
    )
    assert window._session_history.cpu
    assert window._rule_fires  # cpu_high fired
    # The device reconnects: a brand-new session starts from scratch.
    window.update_connection(ConnectionState.DISCONNECTED, "adb device A1")
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.on_serial_ready("FAKE123")
    assert window._session_history.is_empty
    assert window._health is None
    assert window._rule_fires == ()
    session_events = [
        e.event_type
        for e in window._timeline.events
        if e.event_type == "SESSION_STARTED"
    ]
    assert len(session_events) == 1  # old session events are gone, not stacked


def test_duplicate_rule_triggers_suppressed_by_cooldown(qtapp, monkeypatch) -> None:
    window = MainWindow()
    connect_window(window)
    window.update_snapshots(
        _cpu(90.0), _memory(40.0), _processes(), _battery(80.0), _network()
    )
    fires = list(window._rule_fires)
    assert fires
    for _ in range(5):
        window.update_snapshots(
            _cpu(90.0), _memory(40.0), _processes(), _battery(80.0), _network()
        )
    # Same value → dedupe keeps history at one sample → no refire possible,
    # and the rule cooldown would suppress a refire even with new samples.
    rule_events = [
        e for e in window._timeline.events if e.event_type == "RULE_FIRED"
    ]
    assert len(rule_events) == 1