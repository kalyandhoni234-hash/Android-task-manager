"""First-run / setup-flow GUI tests (offscreen Qt, no device needed).

Covers the setup panel states, the multi-device picker, the main window's
setup-vs-dashboard page switching, and the monitor worker's reconfiguration
slots (retry / set_adb_path / select_device) driven through the same flow.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager import __version__
from android_task_manager.adb.exceptions import (
    ADBAmbiguousDeviceError,
    ADBDisconnectedError,
    ADBNoDeviceError,
    ADBNotFoundError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)
from android_task_manager.gui.main_window import MainWindow, wire
from android_task_manager.gui.monitor import ConnectionState, MonitorWorker
from android_task_manager.gui.setup_panel import INSTALL_ADB_STEPS, USB_DEBUGGING_STEPS, SetupPanel


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# SetupPanel state rendering
# ---------------------------------------------------------------------------


def test_setup_panel_initial_scanning(qtapp) -> None:
    panel = SetupPanel()
    assert "Connecting" in panel._title.text()


def test_setup_panel_adb_missing_state(qtapp) -> None:
    panel = SetupPanel()
    panel.show_state(ConnectionState.ADB_MISSING, "adb executable was not found")
    assert panel._title.text() == "ADB not found"
    assert not panel._locate.isHidden()
    assert not panel._retry.isHidden()
    assert not panel._install_help.isHidden()


def test_setup_panel_no_device_state(qtapp) -> None:
    panel = SetupPanel()
    panel.show_state(ConnectionState.DISCONNECTED, "No authorized device")
    assert panel._title.text() == "No Android device detected"
    assert not panel._retry.isHidden()
    assert not panel._usb_help.isHidden()
    assert panel._locate.isHidden()


def test_setup_panel_unauthorized_state(qtapp) -> None:
    panel = SetupPanel()
    panel.show_state(ConnectionState.UNAUTHORIZED, "unauthorized")
    assert panel._title.text() == "Authorization required"
    assert "Allow" in panel._message.text()
    assert not panel._usb_help.isHidden()


def test_setup_panel_offline_state(qtapp) -> None:
    panel = SetupPanel()
    panel.show_state(ConnectionState.OFFLINE, "device offline")
    assert panel._title.text() == "Device is offline"
    assert not panel._retry.isHidden()


def test_setup_panel_generic_error_shows_detail(qtapp) -> None:
    panel = SetupPanel()
    panel.show_state(ConnectionState.ADB_ERROR, "some adb failure")
    assert panel._title.text() == "Connection problem"
    assert "some adb failure" in panel._message.text()
    assert not panel._retry.isHidden()


def test_setup_panel_emits_action_signals(qtapp) -> None:
    panel = SetupPanel()
    panel.show_state(ConnectionState.ADB_MISSING, "")
    actions: list[str] = []
    panel.retry_requested.connect(lambda: actions.append("retry"))
    panel.locate_requested.connect(lambda: actions.append("locate"))
    panel.usb_help_requested.connect(lambda: actions.append("usb"))
    panel.install_help_requested.connect(lambda: actions.append("install"))
    panel._retry.click()
    panel._locate.click()
    panel._usb_help.click()
    panel._install_help.click()
    assert actions == ["retry", "locate", "usb", "install"]


def test_setup_panel_help_texts_are_actionable(qtapp) -> None:
    assert "USB debugging" in USB_DEBUGGING_STEPS
    assert "developer.android.com" in INSTALL_ADB_STEPS


def test_setup_panel_device_list_and_selection(qtapp) -> None:
    panel = SetupPanel()
    panel.show_state(ConnectionState.MULTIPLE_DEVICES, "")
    panel.set_devices(
        [
            {"serial": "A1", "state": "device", "label": "vivo V2026", "android_version": "11"},
            {"serial": "B2", "state": "unauthorized", "label": "Pixel 8", "android_version": ""},
        ]
    )
    assert panel._devices.count() == 2
    assert "vivo V2026" in panel._devices.item(0).text()
    assert "Android 11" in panel._devices.item(0).text()
    assert "unauthorized" in panel._devices.item(1).text()
    # Only the authorized row can be connected.
    panel._devices.setCurrentRow(1)
    assert not panel._connect_btn.isEnabled()
    panel._devices.setCurrentRow(0)
    assert panel._connect_btn.isEnabled()

    selected: list[str] = []
    panel.device_selected.connect(selected.append)
    panel._connect_btn.click()
    assert selected == ["A1"]


def test_setup_panel_emits_refresh(qtapp) -> None:
    panel = SetupPanel()
    panel.show_state(ConnectionState.MULTIPLE_DEVICES, "")
    panel.set_devices([{"serial": "A1", "state": "device", "label": "x", "android_version": ""}])
    refreshed: list[bool] = []
    panel.refresh_requested.connect(lambda: refreshed.append(True))
    panel._refresh.click()
    assert refreshed == [True]


# ---------------------------------------------------------------------------
# MainWindow: setup/dashboard page switching
# ---------------------------------------------------------------------------


def test_window_starts_on_setup_page(qtapp) -> None:
    window = MainWindow()
    assert window._stack.currentIndex() == 0  # setup panel first
    assert window.windowTitle() == f"Android Task Manager {__version__}"


def test_window_switches_to_dashboard_on_connect(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "")
    assert window._stack.currentIndex() == 1
    assert window.device._status.text() == "\u25cf Connected"


def test_window_switches_back_on_disconnect(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "")
    window.update_connection(ConnectionState.DISCONNECTED, "gone")
    assert window._stack.currentIndex() == 0
    assert window.setup._title.text() == "No Android device detected"


def test_window_forwards_first_run_signals(qtapp) -> None:
    window = MainWindow()
    actions: list[str] = []
    window.retry_requested.connect(lambda: actions.append("retry"))
    window.locate_requested.connect(lambda: actions.append("locate"))
    window.device_connect_requested.connect(lambda serial: actions.append(f"pick:{serial}"))
    window.setup.show_state(ConnectionState.MULTIPLE_DEVICES, "")
    window.setup.set_devices([{"serial": "A1", "state": "device", "label": "x", "android_version": ""}])
    window.setup._retry.click()
    window.setup._locate.click()
    window.setup._connect_btn.click()
    assert actions == ["retry", "locate", "pick:A1"]


def test_window_devices_slot_populates_picker(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.MULTIPLE_DEVICES, "")
    window.update_devices(
        [{"serial": "A1", "state": "device", "label": "vivo V2026", "android_version": "11"}]
    )
    assert window.setup._devices.count() == 1
    assert "vivo V2026" in window.setup._devices.item(0).text()


# ---------------------------------------------------------------------------
# MonitorWorker reconfiguration slots (fakes record, no thread)
# ---------------------------------------------------------------------------


class _RecordingConnection:
    """CommandRunner stand-in that can switch adb path and serial."""

    def __init__(self) -> None:
        self.adb_path = "default"
        self.device_serial: str | None = None
        self.verify_calls = 0
        self.connect_fail: BaseException | None = None

    def set_adb_path(self, path: str) -> None:
        self.adb_path = path

    def set_device_serial(self, serial: str | None) -> None:
        self.device_serial = serial

    def verify_available(self) -> None:
        self.verify_calls += 1

    def require_device(self) -> str:
        if self.connect_fail is not None:
            raise self.connect_fail
        return self.device_serial or "A1"

    def shell(self, args, timeout=None) -> str:
        if self.connect_fail is not None:
            raise self.connect_fail
        return ""

    def list_devices(self):
        return []

    def get_device_details(self, serial: str) -> dict[str, str]:
        return {}


def test_worker_retry_reconnects(qtapp) -> None:
    connection = _RecordingConnection()
    worker = MonitorWorker(connection=connection)
    states: list = []
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))
    connection.connect_fail = ADBNoDeviceError("none")
    worker.retry()
    assert states[-1][0] is ConnectionState.DISCONNECTED
    connection.connect_fail = None
    worker.retry()
    assert states[-1][0] is ConnectionState.CONNECTED


def test_worker_set_adb_path_forwards_to_connection_and_reconnects(qtapp) -> None:
    connection = _RecordingConnection()
    worker = MonitorWorker(connection=connection)
    worker.set_adb_path("C:\\apps\\adb.exe")
    assert connection.adb_path == "C:\\apps\\adb.exe"
    assert connection.verify_calls >= 1


def test_worker_select_device_pins_serial_and_connects(qtapp) -> None:
    connection = _RecordingConnection()
    worker = MonitorWorker(connection=connection)
    states: list = []
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))
    worker.select_device("B2")
    assert connection.device_serial == "B2"
    assert states[-1][0] is ConnectionState.CONNECTED


def test_worker_connect_maps_every_user_state(qtapp) -> None:
    cases = [
        (ADBNotFoundError("not found"), ConnectionState.ADB_MISSING),
        (ADBNoDeviceError("none"), ConnectionState.DISCONNECTED),
        (ADBUnauthorizedError("denied"), ConnectionState.UNAUTHORIZED),
        (ADBDisconnectedError("offline"), ConnectionState.OFFLINE),
        (ADBTimeoutError("cmd", 10.0), ConnectionState.TIMEOUT),
    ]
    for failure, expected in cases:
        connection = _RecordingConnection()
        connection.connect_fail = failure
        worker = MonitorWorker(connection=connection)
        states: list = []
        worker.connection_changed.connect(
            lambda state, detail, sink=states: sink.append((state, detail))
        )
        worker.retry()
        assert states and states[-1][0] is expected, f"{failure!r} -> {states}"


def test_worker_tick_reports_mid_session_offline(qtapp) -> None:
    """A device that drops mid-sampling surfaces the clean offline state."""
    connection = _RecordingConnection()
    worker = MonitorWorker(connection=connection)
    states: list = []
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))
    connection.connect_fail = ADBDisconnectedError("device offline")
    worker.tick()
    assert states and states[-1][0] is ConnectionState.OFFLINE
    connection.connect_fail = None
    worker.tick()
    assert states and states[-1][0] is not ConnectionState.OFFLINE


class _AmbiguousConnection(_RecordingConnection):
    """Presents multiple devices, with details, when asked to enumerate."""

    def __init__(self) -> None:
        super().__init__()
        self.device_rows = [
            {"serial": "A1", "state": "device", "label": "vivo V2026", "android_version": "11"},
            {"serial": "B2", "state": "offline", "label": "B2", "android_version": ""},
        ]
        self.connect_fail = ADBAmbiguousDeviceError(["A1", "B2"])

    def list_devices(self):
        class _Row:
            def __init__(self, serial: str, state: str) -> None:
                self.serial = serial
                self.state = state

        return [_Row(d["serial"], d["state"]) for d in self.device_rows]

    def get_device_details(self, serial: str) -> dict[str, str]:
        for row in self.device_rows:
            if row["serial"] == serial:
                return {
                    "ro.product.manufacturer": row["label"].split()[0],
                    "ro.product.model": row["label"].split()[1],
                    "ro.build.version.release": row["android_version"],
                }
        return {}


def test_worker_multiple_devices_emits_list_and_state(qtapp) -> None:
    connection = _AmbiguousConnection()
    worker = MonitorWorker(connection=connection)
    states: list = []
    device_lists: list = []
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))
    worker.devices_available.connect(device_lists.append)
    worker.retry()
    assert states[-1][0] is ConnectionState.MULTIPLE_DEVICES
    assert device_lists and device_lists[0][0]["serial"] == "A1"
    assert device_lists[0][0]["label"] == "vivo V2026"
    assert device_lists[0][0]["android_version"] == "11"


def test_wire_connects_devices_signal(qtapp) -> None:
    window = MainWindow()
    connection = _AmbiguousConnection()
    worker = MonitorWorker(connection=connection)
    wire(window, worker)
    worker._connect()
    assert window.setup._devices.count() == 2
    assert window._stack.currentIndex() == 0


def test_worker_run_recovers_after_failure(qtapp, monkeypatch) -> None:
    """The run loop re-attempts connection until it succeeds (hot-plug)."""
    import threading

    connection = _RecordingConnection()
    worker = MonitorWorker(connection=connection)
    states: list = []
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))
    monkeypatch.setattr("android_task_manager.gui.monitor.time.sleep", lambda _s: None)
    monkeypatch.setattr("android_task_manager.gui.monitor.time.monotonic", lambda: 0.0)

    attempts = {"count": 0}

    def flaky_require_device() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ADBNoDeviceError("device not attached yet")
        return "A1"

    connection.require_device = flaky_require_device
    threading.Timer(0.05, lambda: setattr(worker, "_stopped", True)).start()
    worker.run()
    assert states[0][0] is ConnectionState.DISCONNECTED
    assert ConnectionState.CONNECTED in {state for state, _ in states}


# ---------------------------------------------------------------------------
# Hygiene: the setup panel stays presentation-only
# ---------------------------------------------------------------------------


def test_setup_panel_does_not_talk_to_adb() -> None:
    from android_task_manager.gui import setup_panel

    source = Path(setup_panel.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "ConnectionManager" not in source
    assert "shell(" not in source