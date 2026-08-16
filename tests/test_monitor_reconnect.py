"""Monitor disconnect / stale-data invalidation / reconnect tests.

The monitor worker runs synchronously (``_connect`` + ``tick``) against a
scripted fake connection: no thread, no device, no subprocess. Verifies the
Phase-1 contract: when the device is lost, cached telemetry is invalidated,
an unambiguous empty snapshot is published, and the pipeline re-establishes
itself — collecting everything fresh — once the device is back.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager.adb.exceptions import ADBDisconnectedError, ADBNoDeviceError
from android_task_manager.cpu.models import CPUSnapshot
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
        "                        st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode ref pointer drops\n"
    ),
    "pm list packages -U": (
        "package:com.google.android.youtube uid:10181\n"
        "package:com.instagram.android uid:10203\n"
    ),
}


class _ScriptedConnection:
    """CommandRunner stand-in: normal until ``fail`` is set, then it fails."""

    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
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


def test_device_loss_invalidates_cache_and_emits_empty_snapshot(qtapp) -> None:
    connection = _ScriptedConnection(_RESPONSES)
    worker = _connected_worker(connection)
    assert worker._cpu is not None
    assert worker._memory is not None
    assert worker._processes is not None
    assert worker._battery is not None

    emitted: list = []
    states: list = []
    worker.snapshots.connect(lambda *args: emitted.append(args))
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))

    connection.fail = ADBNoDeviceError("none")
    worker.tick()

    assert ConnectionState.DISCONNECTED in {state for state, _ in states}
    # Stale telemetry is gone — never presented as current.
    assert worker._cpu is None
    assert worker._memory is None
    assert worker._processes is None
    assert worker._battery is None
    assert worker._network is None
    assert worker._network_investigation is None
    # The pipeline published one unambiguous empty snapshot.
    assert emitted and emitted[-1] == (None, None, None, None, None)
    # The run loop will re-establish the connection from scratch.
    assert worker._connected is False


def test_reconnect_collects_fresh_after_loss(qtapp) -> None:
    connection = _ScriptedConnection(_RESPONSES)
    worker = _connected_worker(connection)
    old_cpu = worker._cpu
    assert isinstance(old_cpu, CPUSnapshot)

    connection.fail = ADBNoDeviceError("none")
    worker.tick()
    assert worker._cpu is None

    # The device is back; the connect path re-runs and every collector
    # re-samples immediately (the cache was invalidated, not replayed).
    connection.fail = None
    worker._connect()
    assert worker._connected is True
    worker.tick()
    assert worker._cpu is not None
    assert worker._memory is not None
    assert worker._processes is not None
    assert worker._battery is not None
    # A fresh collection, not the old cached snapshot.
    assert worker._cpu is not old_cpu


def test_connect_failure_invalidates_stale_cache(qtapp) -> None:
    connection = _ScriptedConnection(_RESPONSES)
    worker = _connected_worker(connection)
    assert worker._cpu is not None

    connection.fail = ADBDisconnectedError("Device FAKE123 is present but offline.")
    worker._connect()

    assert worker._connected is False
    assert worker._cpu is None
    assert worker._memory is None


def test_transient_single_collector_failure_keeps_cache(qtapp) -> None:
    """A transient collector hiccup is not a device loss: cached data stays."""
    connection = _ScriptedConnection(_RESPONSES)
    worker = _connected_worker(connection)

    original = worker._battery
    assert original is not None

    # Only the battery read fails this tick; CPU and the rest succeed.
    responses = dict(_RESPONSES)
    responses["dumpsys battery"] = ""
    connection.responses = responses
    worker.tick()

    # Battery failed (COLLECTOR_ERROR) but the device did not vanish: the
    # pipeline stays connected and the last-known-good cache is kept.
    assert worker._battery is original
    assert worker._cpu is not None
    assert worker._connected is True
    # The next successful read replaces the cached snapshot (the failed
    # attempt consumed the battery slot for this interval, so force a resample).
    connection.responses = _RESPONSES
    worker._last_battery_at = 0.0
    worker.tick()
    assert worker._battery is not None
    assert worker._battery is not original


def test_emit_snapshots_without_device_never_contains_stale_data(qtapp) -> None:
    connection = _ScriptedConnection(_RESPONSES)
    worker = _connected_worker(connection)

    emitted: list = []
    worker.snapshots.connect(lambda *args: emitted.append(args))

    connection.fail = ADBNoDeviceError("none")
    worker.tick()

    for snapshot in emitted:
        assert all(item is None for item in snapshot), "stale telemetry leaked"