"""Headless GUI tests for the Intelligence page BACKGROUND USER APPS section.

Covers: human-readable name rendering with the package name as secondary
technical detail, foreground-exclusion, disconnect clears state, reconnect
does not resurrect stale applications, selection emits a detail request, the
v0.7 action capability gate is reused unchanged for background apps, and the
background view is built purely from already-collected snapshots (no extra
ADB polling / no blocking device call on the GUI thread).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from android_task_manager.applications import (
    AppCategory,
    AppInfo,
    ApplicationSnapshot,
)
from android_task_manager.background.collector import ForegroundCollector
from android_task_manager.background.models import ForegroundSnapshot
from android_task_manager.gui.action_worker import ActionWorker
from android_task_manager.gui.apps_worker import AppsWorker
from android_task_manager.gui.main_window import MainWindow, wire, wire_actions, wire_apps
from android_task_manager.gui.monitor import ConnectionState, MonitorWorker
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _memory(used_percent: float = 30.0) -> MemorySnapshot:
    return MemorySnapshot(
        timestamp=1.0,
        total_kb=4_000_000,
        free_kb=0,
        available_kb=int(4_000_000 * (1 - used_percent / 100.0)),
        buffers_kb=0,
        cached_kb=0,
        swap_cached_kb=0,
    )


def _processes() -> ProcessSnapshot:
    return ProcessSnapshot(
        timestamp=1.0,
        processes=[
            ProcessInfo(
                pid=8150,
                name="com.whatsapp",
                uid=10001,
                state="S",
                cpu_percent=0.6,
                memory_percent=4.0,
                category=ProcessCategory.USER,
            ),
            ProcessInfo(
                pid=8151,
                name="com.whatsapp:push",
                uid=10001,
                state="S",
                cpu_percent=0.2,
                memory_percent=2.0,
                category=ProcessCategory.USER,
            ),
            ProcessInfo(
                pid=9000,
                name="com.instagram.android",
                uid=10002,
                state="S",
                cpu_percent=0.8,
                memory_percent=5.0,
                category=ProcessCategory.USER,
            ),
        ],
    )


def _inventory() -> ApplicationSnapshot:
    return ApplicationSnapshot(
        timestamp=1.0,
        applications=[
            AppInfo(package_name="com.whatsapp", uid=10001, category=AppCategory.USER,
                    apk_path="/data/app/com.whatsapp/base.apk"),
            AppInfo(package_name="com.instagram.android", uid=10002, category=AppCategory.USER,
                    apk_path="/data/app/com.instagram/base.apk"),
            AppInfo(package_name="com.android.settings", uid=1000, category=AppCategory.SYSTEM),
        ],
    )


def _foreground(package: str | None = "com.launcher") -> ForegroundSnapshot:
    return ForegroundSnapshot(timestamp=1.0, package_name=package, available=package is not None)


class _FakeRunner:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[list[str]] = []
        self.fail: BaseException | None = None

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        if self.fail is not None:
            raise self.fail
        return self.responses.get(" ".join(args), "")


class _FakeConnection:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[list[str]] = []
        self.fail: BaseException | None = None

    def verify_available(self) -> None:
        pass

    def require_device(self) -> str:
        return "FAKE123"

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        if self.fail is not None:
            raise self.fail
        return self.responses.get(" ".join(args), "")


def _wire(window: MainWindow, with_apps: bool = True) -> tuple[_FakeConnection, _FakeRunner | None]:
    monitor_connection = _FakeConnection()
    monitor = MonitorWorker(connection=monitor_connection, network_investigation_interval=0.0)
    actions = ActionWorker(connection=_FakeRunner(), timeout=3.0)
    window._monitor = monitor
    window._actions = actions
    wire(window, monitor)
    wire_actions(window, monitor, actions)
    apps_runner = None
    if with_apps:
        apps_runner = _FakeRunner()
        apps = AppsWorker(connection=apps_runner, timeout=3.0)
        wire_apps(window, monitor, apps, actions)
        window._apps = apps
    return monitor_connection, apps_runner


def _connect(window: MainWindow) -> None:
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.on_serial_ready("FAKE123")


def _feed_background_data(window: MainWindow) -> None:
    window.update_snapshots(None, _memory(), _processes(), None, None)
    window.on_apps_inventory_ready(_inventory())
    window.update_foreground(_foreground())


# ---------------------------------------------------------------------------
# Section presence + rendering
# ---------------------------------------------------------------------------


def test_background_section_present(qtapp) -> None:
    window = MainWindow()
    assert window.intelligence._background_widget is not None
    texts = [w.text() for w in window.intelligence.findChildren(QLabel)]
    assert any(t == "BACKGROUND USER APPS" for t in texts)
    assert any("User applications currently running in the background" in t for t in texts)


def test_gui_renders_application_name_with_package_secondary(qtapp) -> None:
    window = MainWindow()
    _wire(window, with_apps=False)
    _connect(window)
    window._app_labels = {"com.whatsapp": "WhatsApp"}
    _feed_background_data(window)
    table = window.intelligence._background_widget._table
    assert table.rowCount() == 2  # whatsapp (aggregated) + instagram
    names = {table.item(r, 0).text() for r in range(table.rowCount())}
    packages = {table.item(r, 1).text() for r in range(table.rowCount())}
    assert "WhatsApp" in names
    assert "com.whatsapp" in packages
    # The package name remains visible as secondary technical information.
    assert "com.instagram.android" in packages


def test_package_name_shown_when_label_unresolved(qtapp) -> None:
    window = MainWindow()
    _wire(window, with_apps=False)
    _connect(window)
    window._app_labels = {}  # no labels resolved -> fall back to package
    _feed_background_data(window)
    table = window.intelligence._background_widget._table
    names = {table.item(r, 0).text() for r in range(table.rowCount())}
    assert "com.whatsapp" in names


def test_aggregated_process_count_and_state_rendered(qtapp) -> None:
    window = MainWindow()
    _wire(window, with_apps=False)
    _connect(window)
    _feed_background_data(window)
    table = window.intelligence._background_widget._table
    for r in range(table.rowCount()):
        if table.item(r, 1).text() == "com.whatsapp":
            assert table.item(r, 4).text() == "2"  # 2 processes aggregated
            assert table.item(r, 5).text() == "Background"  # foreground != whatsapp
            return
    raise AssertionError("com.whatsapp row not found")


# ---------------------------------------------------------------------------
# Phase 10: disconnect / reconnect
# ---------------------------------------------------------------------------


def test_disconnect_clears_background_state(qtapp) -> None:
    window = MainWindow()
    _wire(window, with_apps=False)
    _connect(window)
    window._app_labels = {"com.whatsapp": "WhatsApp"}
    _feed_background_data(window)
    assert window._background_apps is not None
    window.update_connection(ConnectionState.DISCONNECTED, "gone")
    assert window._background_apps is None
    assert window.intelligence._background_widget._table.rowCount() == 0
    assert "No device connected" in window.intelligence._background_widget._status.text()


def test_reconnect_does_not_resurrect_stale_apps(qtapp) -> None:
    window = MainWindow()
    _wire(window, with_apps=False)
    _connect(window)
    _feed_background_data(window)
    assert any(e.package_name == "com.whatsapp" for e in window._background_apps.entries)

    # Disconnect, then reconnect with a DIFFERENT inventory (WhatsApp gone).
    window.update_connection(ConnectionState.DISCONNECTED, "gone")
    window.update_connection(ConnectionState.CONNECTED, "adb device A1")
    window.on_serial_ready("FAKE123")
    window.update_snapshots(
        None, _memory(),
        ProcessSnapshot(
            timestamp=1.0,
            processes=[
                ProcessInfo(pid=9000, name="com.instagram.android", uid=10002, state="S",
                            cpu_percent=0.8, memory_percent=5.0, category=ProcessCategory.USER),
            ],
        ),
        None, None,
    )
    window.on_apps_inventory_ready(
        ApplicationSnapshot(
            timestamp=1.0,
            applications=[AppInfo(package_name="com.instagram.android", uid=10002,
                                  category=AppCategory.USER)],
        )
    )
    window.update_foreground(_foreground())
    packages = {e.package_name for e in window._background_apps.entries}
    assert "com.whatsapp" not in packages
    assert "com.instagram.android" in packages


# ---------------------------------------------------------------------------
# Selection + action gating (Phase 7)
# ---------------------------------------------------------------------------


def test_selecting_background_app_requests_details(qtapp) -> None:
    window = MainWindow()
    _wire(window, with_apps=False)
    _connect(window)
    _feed_background_data(window)
    requested: list[str] = []
    window.intelligence.background_detail_requested.connect(requested.append)
    table = window.intelligence._background_widget._table
    table.selectRow(0)
    assert requested and requested[0] in {"com.whatsapp", "com.instagram.android"}


def test_system_app_excluded_from_background_list(qtapp) -> None:
    window = MainWindow()
    _wire(window, with_apps=False)
    _connect(window)
    # System app with a running process must be excluded from the list.
    window.update_snapshots(
        None, _memory(),
        ProcessSnapshot(
            timestamp=1.0,
            processes=[ProcessInfo(pid=1, name="com.android.settings", uid=1000, state="S",
                                  cpu_percent=1.0, memory_percent=1.0,
                                  category=ProcessCategory.SYSTEM)],
        ),
        None, None,
    )
    window.on_apps_inventory_ready(_inventory())
    window.update_foreground(_foreground())
    assert window._background_apps is not None
    assert all(e.package_name != "com.android.settings" for e in window._background_apps.entries)


def test_background_force_stop_emits_for_user_app_with_confirmation(qtapp, monkeypatch) -> None:
    window = MainWindow()
    _wire(window, with_apps=False)
    _connect(window)
    _feed_background_data(window)
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    emitted: list[tuple[str, str]] = []
    window.action_requested.connect(lambda a, p: emitted.append((a, p)))
    window._on_background_action_clicked("force_stop", "com.whatsapp")
    assert emitted == [("force_stop", "com.whatsapp")]


def test_background_action_rejected_for_unknown_package(qtapp) -> None:
    window = MainWindow()
    _wire(window, with_apps=False)
    _connect(window)
    _feed_background_data(window)
    emitted: list[tuple[str, str]] = []
    window.action_requested.connect(lambda a, p: emitted.append((a, p)))
    window._on_background_action_clicked("force_stop", "")
    window._on_background_action_clicked("force_stop", "com.not.installed")
    assert emitted == []


# ---------------------------------------------------------------------------
# Phase 9 / 16: no extra polling, no blocking ADB call
# ---------------------------------------------------------------------------


def test_background_build_consumes_cached_snapshots_only(qtapp) -> None:
    """Building the background view must not issue any ADB call itself — it
    only reads snapshots already published by the monitor / apps worker."""
    window = MainWindow()
    monitor_connection, _ = _wire(window, with_apps=False)
    _connect(window)
    _feed_background_data(window)
    calls_before = len(monitor_connection.calls)
    window._build_background_apps()
    assert len(monitor_connection.calls) == calls_before


def test_monitor_foreground_reuses_existing_timer_no_extra_loop(qtapp) -> None:
    """The foreground sampler extends the existing MonitorWorker timer; it
    does not spin up a second polling loop."""
    monitor_connection = _FakeConnection()
    monitor = MonitorWorker(connection=monitor_connection, network_investigation_interval=0.0)
    # The single sampling timer is created when the worker loop starts.
    monitor.run()
    try:
        timers = monitor.findChildren(QTimer)
        assert len(timers) == 1  # one timer for the whole sampling loop
    finally:
        monitor.stop()
    assert isinstance(monitor._foreground_collector, ForegroundCollector)


def test_foreground_signal_emitted_by_monitor_tick(qtapp) -> None:
    monitor_connection = _FakeConnection(
        {
            "dumpsys activity activities": (
                "mResumedActivity: ActivityRecord{abc u0 com.launcher/.Main t1}\n"
            )
        }
    )
    monitor = MonitorWorker(connection=monitor_connection, network_investigation_interval=0.0)
    emitted: list[object] = []
    monitor.foreground_snapshot.connect(lambda s: emitted.append(s))
    monitor._foreground_collector.sample = lambda: ForegroundSnapshot(
        timestamp=1.0, package_name="com.launcher", available=True
    )
    monitor.tick()
    assert emitted and emitted[0] is not None
    assert emitted[0].package_name == "com.launcher"
