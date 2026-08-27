"""Focused RED tests for Priority #9: transient collector failure vs disconnect.

The core contract:
- Genuine ADB/device-loss exception → full disconnect handling.
- Transient collector failure → status warning only, NO telemetry reset,
  NO phantom timeline event, NO session destruction, NO UI flap to setup.

Tests verify externally observable behavior at the consumer level.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager.adb.exceptions import (
    ADBDisconnectedError,
    ADBNoDeviceError,
)
from android_task_manager.gui.monitor import ConnectionState, MonitorWorker

_RESPONSES = {
    "getprop ro.product.manufacturer": "vivo",
    "getprop ro.product.model": "V2026",
    "getprop ro.build.version.release": "11",
    "cat /proc/stat": (
        "cpu  1234 0 5678 91011 12 0 0 0 0 0\n"
        "cpu0 100 0 200 3000 0 0 0 0 0 0\n"
        "cpu1 100 0 200 3000 0 0 0 0 0 0\n"
    ),
    "cat /proc/meminfo": (
        "MemTotal:        2865476 kB\n"
        "MemFree:          117296 kB\n"
        "MemAvailable:     842000 kB\n"
        "Buffers:           26924 kB\n"
        "Cached:           887532 kB\n"
        "SwapCached:            0 kB\n"
    ),
    "ps -A -o PID,UID,NAME": "PID UID NAME\n1 0 init\n100 1000 system_server\n",
    "top -n 1": (
        "Tasks: 2 total, 1 running, 1 sleeping\n"
        "  PID  USER  PR  NI  VIRT  RES  SHR  S  %CPU  %MEM  TIME+  ARGS\n"
        "100 root 20 0 0K 0K 0K S 5.0 2.0 0:00.10 system_server\n"
    ),
    "dumpsys battery": (
        "Current Battery Service state:\n"
        "  AC powered: false\n"
        "  USB powered: true\n"
        "  Wireless powered: false\n"
        "  status: 2\n"
        "  health: 2\n"
        "  present: true\n"
        "  level: 38\n"
        "  scale: 100\n"
        "  voltage: 4116\n"
        "  temperature: 341\n"
    ),
    "cat /proc/net/dev": (
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
        " wlan0: 112932964 105705 0 0 0 0 0 0 11157432 31390 577 0 0 0 0 0\n"
        "  ccmni3:  1324567   8129 2 0 0 0 0 0   893241   6115 1 0 0 0 0 0\n"
        "  lo:      18401   2964 0 0 0 0 0 0   18401   2964 0 0 0 0 0 0\n"
    ),
    "cat /proc/net/tcp": (
        "sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n"
    ),
    "cat /proc/net/tcp6": (
        "sl local_address                         remote_address"
        "                        st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode ref pointer drops\n"
    ),
    "cat /proc/net/udp": (
        "sl local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops\n"
    ),
    "cat /proc/net/udp6": (
        "sl local_address                         remote_address"
        "                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops\n"
    ),
    "pm list packages -U": (
        "package:com.google.android.youtube uid:10181\n"
        "package:com.instagram.android uid:10203\n"
    ),
}


class _ScriptedConnection:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = dict(responses)
        self.fail: BaseException | None = None
        self.calls: list[list[str]] = []

    def verify_available(self) -> None:
        pass

    def require_device(self) -> str:
        return "FAKE123"

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        if self.fail is not None:
            raise self.fail
        return self.responses.get(" ".join(args), "")


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _connected_worker(connection: _ScriptedConnection) -> MonitorWorker:
    worker = MonitorWorker(connection=connection, network_investigation_interval=0.0)
    worker._connect()
    worker.tick()
    assert worker._cpu is not None
    return worker


def _simulate_battery_failure(worker: MonitorWorker, connection: _ScriptedConnection) -> None:
    """Make only the battery collector fail (empty response → parse error)."""
    connection.responses["dumpsys battery"] = ""
    worker._last_battery_at = 0.0


# ======================================================================
# 1. Genuine device loss MUST still trigger full disconnect handling
# ======================================================================


class TestGenuineDeviceLossStillWorks:
    def test_device_loss_emits_disconnect_state(self, qtapp) -> None:
        connection = _ScriptedConnection(_RESPONSES)
        worker = _connected_worker(connection)
        states: list = []
        worker.connection_changed.connect(lambda state, _d: states.append(state))

        connection.fail = ADBNoDeviceError("none")
        worker.tick()

        assert ConnectionState.DISCONNECTED in states

    def test_device_loss_invalidates_cache(self, qtapp) -> None:
        connection = _ScriptedConnection(_RESPONSES)
        worker = _connected_worker(connection)
        assert worker._cpu is not None

        connection.fail = ADBNoDeviceError("none")
        worker.tick()

        assert worker._cpu is None
        assert worker._memory is None
        assert worker._connected is False

    def test_device_loss_emits_empty_snapshot(self, qtapp) -> None:
        connection = _ScriptedConnection(_RESPONSES)
        worker = _connected_worker(connection)
        emitted: list = []
        worker.snapshots.connect(lambda *args: emitted.append(args))

        connection.fail = ADBNoDeviceError("none")
        worker.tick()

        assert emitted and emitted[-1] == (None, None, None, None, None)


# ======================================================================
# 2. Monitor worker: transient failure preserves state
# ======================================================================


class TestMonitorWorkerTransientFailure:
    def test_collector_error_not_in_loss_states(self) -> None:
        from android_task_manager.gui.monitor import _DEVICE_LOSS_STATES

        assert ConnectionState.COLLECTOR_ERROR not in _DEVICE_LOSS_STATES

    def test_transient_failure_keeps_connected(self, qtapp) -> None:
        connection = _ScriptedConnection(_RESPONSES)
        worker = _connected_worker(connection)

        _simulate_battery_failure(worker, connection)
        worker.tick()

        assert worker._connected is True

    def test_transient_failure_preserves_caches(self, qtapp) -> None:
        connection = _ScriptedConnection(_RESPONSES)
        worker = _connected_worker(connection)
        original_memory = worker._memory
        original_processes = worker._processes
        original_battery = worker._battery

        _simulate_battery_failure(worker, connection)
        worker.tick()

        assert worker._memory is original_memory
        assert worker._processes is original_processes
        assert worker._battery is original_battery

    def test_repeated_failures_keep_connected(self, qtapp) -> None:
        connection = _ScriptedConnection(_RESPONSES)
        worker = _connected_worker(connection)

        for _ in range(5):
            _simulate_battery_failure(worker, connection)
            worker.tick()

        assert worker._connected is True
        assert worker._cpu is not None

    def test_recovery_after_failures(self, qtapp) -> None:
        connection = _ScriptedConnection(_RESPONSES)
        worker = _connected_worker(connection)
        original_battery = worker._battery

        for _ in range(2):
            _simulate_battery_failure(worker, connection)
            worker.tick()

        connection.responses["dumpsys battery"] = _RESPONSES["dumpsys battery"]
        worker._last_battery_at = 0.0
        worker.tick()
        assert worker._battery is not original_battery


# ======================================================================
# 3. PerformanceIntegration: COLLECTOR_ERROR must not destroy session
# ======================================================================


class TestPerformanceIntegrationTransientFailure:
    def test_collector_error_preserves_session(self, qtapp) -> None:
        from android_task_manager.gui.performance_integration import (
            PerformanceIntegration,
        )

        pi = PerformanceIntegration()
        # Start a session with a serial.
        pi._orchestrator.begin_session("FAKE123", timestamp=time.monotonic())
        assert pi.orchestrator.session.device_serial == "FAKE123"

        # Simulate COLLECTOR_ERROR — must NOT end the session.
        pi.on_connection_changed(ConnectionState.COLLECTOR_ERROR, "battery failed")

        # Session must still be alive.
        assert pi.orchestrator.session.device_serial == "FAKE123"

    def test_genuine_disconnect_ends_session(self, qtapp) -> None:
        from android_task_manager.gui.performance_integration import (
            PerformanceIntegration,
        )

        pi = PerformanceIntegration()
        pi._orchestrator.begin_session("FAKE123", timestamp=time.monotonic())
        assert pi.orchestrator.session.device_serial == "FAKE123"

        pi.on_connection_changed(ConnectionState.DISCONNECTED, "device gone")

        assert pi.orchestrator.session.device_serial is None

    def test_timeout_preserves_session(self, qtapp) -> None:
        from android_task_manager.gui.performance_integration import (
            PerformanceIntegration,
        )

        pi = PerformanceIntegration()
        pi._orchestrator.begin_session("FAKE123", timestamp=time.monotonic())

        pi.on_connection_changed(ConnectionState.TIMEOUT, "command timed out")

        assert pi.orchestrator.session.device_serial == "FAKE123"


# ======================================================================
# 4. Main window: COLLECTOR_ERROR must not record phantom disconnect
# ======================================================================


class TestMainWindowTransientFailure:
    """update_connection must not treat COLLECTOR_ERROR as device loss.

    We test by checking the observable side effects: timeline events and
    the connection state stored on the window.
    """

    def _make_minimal_window(self, qtapp):
        """Create a bare MainWindow with only the attributes update_connection reads."""
        from android_task_manager.gui.main_window import MainWindow

        window = MainWindow.__new__(MainWindow)
        window._connection_state = ConnectionState.CONNECTED
        window._device_serial = "FAKE123"
        window._latest_cpu = "cpu_value"
        window._latest_memory = "mem_value"
        window._latest_battery = "batt_value"
        window._latest_network = "net_value"
        window._latest_storage = "stor_value"
        window._latest_processes = "proc_value"
        window._latest_network_investigation = "ni_value"
        window._latest_app_snapshot = "app_value"
        window._latest_foreground = "fg_value"
        window._app_labels = {"pkg": "Label"}
        window._label_requested = {"pkg"}
        window._background_apps = "bg_value"
        window._last_seen_tracker = {}
        window._background_selected = "sel"
        window._verified_packages = {"pkg"}
        window._user_packages = {"pkg"}
        window._diagnostics_report = "diag"
        window._health = "health"
        window._recommendations = ("rec",)
        window._rule_fires = ("rule",)
        window._pending_automation_task = "task"
        window.device_information = "info"
        from unittest.mock import MagicMock

        window._timeline = MagicMock()
        window.device = MagicMock()
        window.connection_strip = MagicMock()
        window.setup = MagicMock()
        window.diagnostics_page = MagicMock()
        window.apps = MagicMock()
        window.intelligence = MagicMock()
        window._stack = MagicMock()
        window._performance = MagicMock()
        window._refresh_performance_page = MagicMock()
        window._refresh_intelligence = MagicMock()
        window._refresh_overview = MagicMock()
        window._refresh_device_page = MagicMock()
        return window

    def test_collector_error_preserves_caches(self, qtapp) -> None:
        window = self._make_minimal_window(qtapp)

        window.update_connection(ConnectionState.COLLECTOR_ERROR, "battery parse error")

        assert window._latest_cpu == "cpu_value"
        assert window._latest_memory == "mem_value"
        assert window._latest_battery == "batt_value"

    def test_collector_error_no_disconnect_timeline(self, qtapp) -> None:
        window = self._make_minimal_window(qtapp)

        window.update_connection(ConnectionState.COLLECTOR_ERROR, "battery parse error")

        for call in window._timeline.record_transition.call_args_list:
            args = str(call)
            assert "disconnected" not in args.lower(), (
                f"Phantom disconnect recorded: {args}"
            )

    def test_collector_error_no_setup_screen(self, qtapp) -> None:
        window = self._make_minimal_window(qtapp)

        window.update_connection(ConnectionState.COLLECTOR_ERROR, "battery parse error")

        # setup.show_state should NOT be called for COLLECTOR_ERROR.
        window.setup.show_state.assert_not_called()

    def test_genuine_disconnect_clears_caches(self, qtapp) -> None:
        window = self._make_minimal_window(qtapp)

        window.update_connection(ConnectionState.DISCONNECTED, "device lost")

        assert window._latest_cpu is None
        assert window._latest_memory is None
        assert window._latest_battery is None

    def test_genuine_disconnect_records_timeline(self, qtapp) -> None:
        window = self._make_minimal_window(qtapp)

        window.update_connection(ConnectionState.DISCONNECTED, "device lost")

        has_disconnect = any(
            "disconnected" in str(call).lower()
            for call in window._timeline.record_transition.call_args_list
        )
        assert has_disconnect

    def test_genuine_disconnect_switches_to_setup(self, qtapp) -> None:
        window = self._make_minimal_window(qtapp)

        window.update_connection(ConnectionState.DISCONNECTED, "device lost")

        window.setup.show_state.assert_called_once()


# ======================================================================
# 5. Mixed: genuine loss must still work
# ======================================================================


class TestMixedErrors:
    def test_genuine_loss_overwrites_state(self, qtapp) -> None:
        connection = _ScriptedConnection(_RESPONSES)
        worker = _connected_worker(connection)

        connection.fail = ADBDisconnectedError("offline")
        worker.tick()

        assert worker._connected is False
        assert worker._cpu is None
