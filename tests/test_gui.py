"""GUI tests: non-visual application logic, runnable without a display.

PySide6 uses the ``offscreen`` Qt platform plugin, so widget construction,
snapshot delivery and the monitor worker are testable headlessly.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# GUI tests require the optional PySide6 extra; without it they skip instead
# of failing collection, so `pip install .` + `python -m pytest` works cleanly.
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager import __version__
from android_task_manager.adb.exceptions import (
    ADBDisconnectedError,
    ADBNoDeviceError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)
from android_task_manager.battery.models import BatteryHealth, BatterySnapshot, BatteryStatus
from android_task_manager.cpu.models import CPUCore, CPUSnapshot
from android_task_manager.gui.inspector_worker import ProcessInspectionWorker
from android_task_manager.gui.interface_classifier import classify_interface
from android_task_manager.gui.main_window import MainWindow, wire, wire_inspector
from android_task_manager.gui.monitor import ConnectionState, MonitorWorker
from android_task_manager.gui.styles import DARK_STYLE
from android_task_manager.gui.widgets.battery_history import BatteryHistoryWidget
from android_task_manager.gui.widgets.battery_widget import BatteryWidget
from android_task_manager.gui.widgets.cpu_history import CPUHistoryWidget
from android_task_manager.gui.widgets.cpu_widget import CPUWidget
from android_task_manager.gui.widgets.device_widget import DeviceWidget
from android_task_manager.gui.widgets.memory_history import MemoryHistoryWidget
from android_task_manager.gui.widgets.memory_widget import MemoryWidget
from android_task_manager.gui.widgets.network_history import NetworkHistoryWidget
from android_task_manager.gui.widgets.network_widget import NetworkWidget
from android_task_manager.gui.widgets.process_widget import ProcessWidget
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.network.models import (
    NetworkInterfaceSnapshot,
    NetworkSnapshot,
    NetworkThroughput,
)
from android_task_manager.network_investigation.models import (
    NetworkInvestigationSnapshot,
    SocketInfo,
)
from android_task_manager.process.inspector_models import ProcessInspectionSnapshot
from android_task_manager.process.models import ProcessInfo, ProcessSnapshot


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Snapshot fixtures
# ---------------------------------------------------------------------------


def cpu_snapshot() -> CPUSnapshot:
    return CPUSnapshot(
        timestamp=1.0,
        aggregate_utilization_percent=12.4,
        cores=[
            CPUCore(core_id=0, utilization_percent=12.0, frequency_khz=1_750_000, frequency_available=True),
            CPUCore(core_id=1, utilization_percent=None, frequency_khz=None, frequency_available=False),
        ],
    )


def memory_snapshot() -> MemorySnapshot:
    return MemorySnapshot(
        timestamp=1.0,
        total_kb=2_865_476,
        free_kb=117_296,
        available_kb=842_000,
        buffers_kb=26_924,
        cached_kb=887_532,
        swap_cached_kb=0,
    )


def process_snapshot() -> ProcessSnapshot:
    return ProcessSnapshot(
        timestamp=1.0,
        processes=[
            ProcessInfo(pid=8150, name="com.heavy.app", uid=10001, state="R", cpu_percent=120.4, memory_percent=2.0, category="user"),
            ProcessInfo(pid=24791, name="com.instagram.android", uid=10203, state="S", cpu_percent=2.9, memory_percent=5.5, category="user"),
            ProcessInfo(pid=90001, name="no.metric.app", uid=None, state=None, cpu_percent=None, memory_percent=None, category="user"),
        ],
    )


def network_snapshot() -> NetworkSnapshot:
    return NetworkSnapshot(
        timestamp=1.0,
        interfaces=[
            NetworkInterfaceSnapshot(
                name="wlan0",
                rx_bytes=112932964,
                tx_bytes=11157432,
                rx_packets=105705,
                tx_packets=31390,
                rx_errors=0,
                tx_errors=577,
                rx_drops=0,
                tx_drops=0,
            ),
            NetworkInterfaceSnapshot(
                name="lo",
                rx_bytes=18401,
                tx_bytes=18401,
                rx_packets=2964,
                tx_packets=2964,
                rx_errors=0,
                tx_errors=0,
                rx_drops=0,
                tx_drops=0,
            ),
        ],
        aggregate_rx_bytes=112932964,
        aggregate_tx_bytes=11157432,
        aggregate_rx_packets=105705,
        aggregate_tx_packets=31390,
        aggregate_rx_errors=0,
        aggregate_tx_errors=577,
        aggregate_rx_drops=0,
        aggregate_tx_drops=0,
        interface_throughput={
            "wlan0": NetworkThroughput(rx_bytes_per_sec=2_097_152.0, tx_bytes_per_sec=380_000.0),
            "lo": NetworkThroughput(rx_bytes_per_sec=0.0, tx_bytes_per_sec=0.0),
        },
        aggregate_throughput=NetworkThroughput(rx_bytes_per_sec=2_097_152.0, tx_bytes_per_sec=380_000.0),
    )


def battery_snapshot() -> BatterySnapshot:
    return BatterySnapshot(
        timestamp=1.0,
        level_percent=38.0,
        scale=100,
        voltage_mv=4116,
        temperature_c=34.1,
        status=BatteryStatus.CHARGING,
        status_raw=2,
        health=BatteryHealth.GOOD,
        health_raw=2,
        present=True,
        ac_powered=False,
        usb_powered=True,
        wireless_powered=False,
        technology="Li-poly",
        charge_counter=361000,
    )


# ---------------------------------------------------------------------------
# Fake connection for the monitor worker
# ---------------------------------------------------------------------------


class _FakeConnection:
    """CommandRunner stand-in returning canned output (empty for unknown keys)."""

    def __init__(self, responses: dict[str, str], fail: BaseException | None = None) -> None:
        self.responses = responses
        self.fail = fail
        self.calls: list[list[str]] = []

    def verify_available(self) -> None:
        pass

    def require_device(self) -> str:
        if isinstance(self.fail, ADBUnauthorizedError):
            raise self.fail
        return "FAKE123"

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        if self.fail is not None:
            raise self.fail
        return self.responses.get(" ".join(args), "")


def _device_responses() -> dict[str, str]:
    return {
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
            "                        st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n"
            "  7: 008102242828E139EBE8095A40AB1FEC:B3B6"
            " 9BFF640000000000000000002711F09D:01BB 08 00000000:00000019"
            " 00:00000000 00000000 10203        0 30828972 1 0000000000000000"
            " 47 4 28 10 -1\n"
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


# ---------------------------------------------------------------------------
# Widget tests (snapshot -> widget)
# ---------------------------------------------------------------------------


def test_gui_imports() -> None:
    from android_task_manager.gui import app, main_window, monitor
    from android_task_manager.gui import widgets as widgets

    assert widgets.panel is not None
    assert monitor.ConnectionState is not None
    assert app.main is not None
    assert main_window.wire is not None
    assert "QFrame#panel" in DARK_STYLE


def test_main_window_constructs(qtapp) -> None:
    window = MainWindow()
    assert window.windowTitle() == f"Android Task Manager {__version__}"
    assert "Connecting" in window.device._status.text()


def test_cpu_widget_receives_snapshot(qtapp) -> None:
    widget = CPUWidget()
    widget.set_snapshot(cpu_snapshot())
    assert widget._overall.text() == "12.4%"
    labels = {}
    for label, _bar, pct, freq in widget._core_rows:
        labels[label.text()] = (pct.text(), freq.text())
    assert labels["Core 0"] == ("12.0%", "1.75 GHz")
    assert labels["Core 1"] == ("N/A", "N/A")


def test_cpu_history_receives_successive_snapshots(qtapp) -> None:
    widget = CPUWidget()
    widget.set_snapshot(cpu_snapshot())
    assert widget._history.samples == [12.4]
    widget.set_snapshot(cpu_snapshot())
    assert widget._history.samples == [12.4, 12.4]


def test_cpu_history_retains_only_recent_window(qtapp) -> None:
    history = CPUHistoryWidget(max_samples=5)
    for index in range(1, 9):
        history.add_sample(float(index))
    assert history.samples == [4.0, 5.0, 6.0, 7.0, 8.0]


def test_cpu_history_handles_first_and_none_samples(qtapp) -> None:
    history = CPUHistoryWidget()
    history.add_sample(None)
    history.add_sample(None)
    assert history.samples == []
    history.add_sample(12.4)
    assert history.samples == [12.4]


def test_cpu_widget_feeds_history_from_snapshot(qtapp) -> None:
    widget = CPUWidget()
    assert widget._history.samples == []  # initial snapshot has no baseline
    widget.set_snapshot(cpu_snapshot())
    assert widget._history.samples == [12.4]


def test_memory_history_retains_and_bounds_samples(qtapp) -> None:
    history = MemoryHistoryWidget(max_samples=5)
    for index in range(1, 9):
        history.add_sample(float(index))
    assert history.samples == [4.0, 5.0, 6.0, 7.0, 8.0]


def test_memory_history_skips_none_samples(qtapp) -> None:
    history = MemoryHistoryWidget()
    history.add_sample(None)
    assert history.samples == []
    history.add_sample(29.4)
    history.add_sample(None)
    assert history.samples == [29.4]


def test_memory_widget_feeds_history_available_share(qtapp) -> None:
    widget = MemoryWidget()
    assert widget._history.samples == []
    widget.set_snapshot(memory_snapshot())
    # 842_000 / 2_865_476 kB available -> the same baseline the headline shows.
    assert widget._history.samples == [pytest.approx(842_000 / 2_865_476 * 100)]


def test_network_history_tracks_download_and_upload(qtapp) -> None:
    history = NetworkHistoryWidget()
    history.add_sample(2_000_000.0, 500_000.0)
    history.add_sample(1_000_000.0, 250_000.0)
    assert history.download_samples == [2_000_000.0, 1_000_000.0]
    assert history.upload_samples == [500_000.0, 250_000.0]


def test_network_history_skips_none_per_series(qtapp) -> None:
    history = NetworkHistoryWidget()
    history.add_sample(None, 42.0)
    assert history.download_samples == []
    assert history.upload_samples == [42.0]


def test_network_history_zero_traffic_and_bounded_window(qtapp) -> None:
    history = NetworkHistoryWidget(max_samples=5)
    for _ in range(9):
        history.add_sample(0.0, 0.0)
    assert history.download_samples == [0.0] * 5
    assert history.upload_samples == [0.0] * 5
    history._plot.grab()  # a zero-only window must still paint


def test_network_widget_feeds_history_from_aggregate(qtapp) -> None:
    widget = NetworkWidget()
    widget.set_snapshot(None)
    assert widget._history.download_samples == []
    widget.set_snapshot(network_snapshot())
    assert widget._history.download_samples == [2_097_152.0]
    assert widget._history.upload_samples == [380_000.0]


def test_battery_history_tracks_and_bounds_level(qtapp) -> None:
    history = BatteryHistoryWidget(max_samples=4)
    for index in range(1, 7):
        history.add_sample(float(index))
    assert history.samples == [3.0, 4.0, 5.0, 6.0]


def test_battery_history_skips_none_samples(qtapp) -> None:
    history = BatteryHistoryWidget()
    history.add_sample(None)
    history.add_sample(38.0)
    assert history.samples == [38.0]


def test_battery_widget_feeds_history_from_level(qtapp) -> None:
    widget = BatteryWidget()
    assert widget._history.samples == []
    widget.set_snapshot(battery_snapshot())
    assert widget._history.samples == [38.0]
    widget.set_snapshot(None)
    assert widget._history.samples == [38.0]  # no fabricated sample on teardown


def test_memory_widget_receives_snapshot(qtapp) -> None:
    widget = MemoryWidget()
    widget.set_snapshot(memory_snapshot())
    # Available is the primary number; used share is a clearly labeled %.
    assert widget._available.text() == "822 MB"
    assert widget._available_caption.text() == "Available"
    assert widget._used.text() == "71% used"
    assert widget._rows["Total"].text() == "2.73 GB"
    assert widget._rows["Free"].text() == "115 MB"
    assert widget._rows["Cached"].text() == "867 MB"
    assert widget._rows["Buffers"].text() == "26 MB"


def test_memory_available_value_is_displayed(qtapp) -> None:
    widget = MemoryWidget()
    widget.set_snapshot(memory_snapshot())
    assert widget._available.text() == "822 MB"
    assert widget._bar.value() == 71


def test_battery_widget_receives_snapshot(qtapp) -> None:
    widget = BatteryWidget()
    widget.set_snapshot(battery_snapshot())
    assert widget._level.text() == "38%"
    assert widget._status.text() == "Charging"
    assert widget._health.text() == "Good"
    assert widget._bar.value() == 38
    assert widget._fields["Temperature"].text() == "34.1 \u00b0C"
    assert widget._fields["Voltage"].text() == "4.116 V"
    assert widget._fields["Technology"].text() == "Li-poly"
    assert widget._fields["Power"].text() == "USB"


def test_battery_compact_layout_renders(qtapp) -> None:
    widget = BatteryWidget()
    widget.set_snapshot(battery_snapshot())
    # Level, status and health share one row; the level bar tracks the level.
    assert widget._level.text() == "38%"
    assert widget._bar.value() == 38
    for field in ("Temperature", "Voltage", "Technology", "Power"):
        assert widget._fields[field].text() != "N/A"


def test_cpu_widget_colors_threshold_levels(qtapp) -> None:
    widget = CPUWidget()
    busy = CPUSnapshot(
        timestamp=1.0,
        aggregate_utilization_percent=90.0,
        cores=[
            CPUCore(core_id=0, utilization_percent=12.0, frequency_khz=1_750_000, frequency_available=True),
            CPUCore(core_id=1, utilization_percent=70.0, frequency_khz=None, frequency_available=False),
        ],
    )
    widget.set_snapshot(busy)
    assert widget._overall.property("level") == "high"
    assert widget._overall.property("mono") is True
    label, _bar, pct, freq = widget._core_rows[0]
    assert pct.property("level") == "normal"
    assert freq.property("mono") is True
    label, _bar, pct, freq = widget._core_rows[1]
    assert pct.property("level") == "elevated"


def test_memory_widget_colors_used_pressure(qtapp) -> None:
    widget = MemoryWidget()
    widget.set_snapshot(memory_snapshot())  # 71% used -> Elevated (amber).
    assert widget._used.property("level") == "elevated"
    assert widget._available.property("mono") is True
    widget.set_snapshot(None)
    assert widget._used.property("level") == "normal"


def test_battery_widget_colors_temperature(qtapp) -> None:
    widget = BatteryWidget()
    widget.set_snapshot(battery_snapshot())  # 34.1 C -> Normal.
    assert widget._fields["Temperature"].property("level") == "normal"
    widget.set_snapshot(replace(battery_snapshot(), temperature_c=46.0))
    assert widget._fields["Temperature"].property("level") == "high"


def test_metric_widgets_use_mono_typography(qtapp) -> None:
    cpu = CPUWidget()
    assert cpu._overall.property("mono") is True
    memory = MemoryWidget()
    assert memory._available.property("mono") is True
    assert memory._rows["Total"].property("mono") is True
    battery = BatteryWidget()
    assert battery._level.property("mono") is True
    assert battery._fields["Voltage"].property("mono") is True
    network = NetworkWidget()
    assert network._down.property("mono") is True
    assert network._up.property("mono") is True


def test_process_widget_receives_snapshot_sorted_by_cpu_desc(qtapp) -> None:
    widget = ProcessWidget()
    widget.set_snapshot(process_snapshot())
    assert widget._table.rowCount() == 3
    assert widget._table.item(0, 0).text() == "8150"
    assert widget._table.item(1, 0).text() == "24791"
    assert widget._table.item(2, 0).text() == "90001"
    assert widget._table.item(0, 1).text() == "120.4%"
    assert widget._table.item(2, 1).text() == "N/A"


def _network_col0(widget) -> list[str]:
    """Collect the text of every first-column cell in the network grid."""
    rendered: list[str] = []
    grid = widget._interface_container.layout()
    for row in range(grid.rowCount()):
        cell = grid.itemAtPosition(row, 0)
        rendered.append(cell.widget().text() if cell is not None else "")
    return rendered


def test_network_widget_receives_snapshot(qtapp) -> None:
    widget = NetworkWidget()
    widget.set_snapshot(network_snapshot())
    assert widget._down.text() == "2.00 MB/s"
    assert widget._up.text() == "371 KB/s"
    rendered = _network_col0(widget)
    # wlan0 is active and shown under its WiFi category; idle lo is hidden.
    assert "wlan0" in rendered
    assert "Wi-Fi" in rendered
    assert "lo" not in rendered


def test_network_widget_no_snapshot_uses_na(qtapp) -> None:
    widget = NetworkWidget()
    widget.set_snapshot(None)
    assert widget._down.text() == "N/A"
    assert widget._up.text() == "N/A"
    assert "No network data" in _network_col0(widget)


def test_network_widget_hides_zero_throughput_interfaces(qtapp) -> None:
    snapshot = NetworkSnapshot(
        timestamp=1.0,
        interfaces=[
            NetworkInterfaceSnapshot(
                name="wlan0", rx_bytes=1, tx_bytes=1, rx_packets=1, tx_packets=1,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0,
            ),
            NetworkInterfaceSnapshot(
                name="ccmni5", rx_bytes=0, tx_bytes=0, rx_packets=0, tx_packets=0,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0,
            ),
            NetworkInterfaceSnapshot(
                name="ccmni12", rx_bytes=0, tx_bytes=0, rx_packets=0, tx_packets=0,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0,
            ),
            NetworkInterfaceSnapshot(
                name="dummy0", rx_bytes=0, tx_bytes=0, rx_packets=0, tx_packets=0,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0,
            ),
        ],
        aggregate_rx_bytes=1,
        aggregate_tx_bytes=1,
        interface_throughput={
            "wlan0": NetworkThroughput(rx_bytes_per_sec=5000.0, tx_bytes_per_sec=1000.0),
            "ccmni5": NetworkThroughput(rx_bytes_per_sec=0.0, tx_bytes_per_sec=0.0),
            "ccmni12": NetworkThroughput(rx_bytes_per_sec=0.0, tx_bytes_per_sec=0.0),
            "dummy0": NetworkThroughput(rx_bytes_per_sec=0.0, tx_bytes_per_sec=0.0),
        },
        aggregate_throughput=NetworkThroughput(rx_bytes_per_sec=5000.0, tx_bytes_per_sec=1000.0),
    )
    widget = NetworkWidget()
    widget.set_snapshot(snapshot)
    rendered = _network_col0(widget)
    assert "wlan0" in rendered
    assert "ccmni5" not in rendered
    assert "ccmni12" not in rendered
    assert "dummy0" not in rendered


def test_network_widget_show_all_reveals_idle_interfaces(qtapp) -> None:
    snapshot = NetworkSnapshot(
        timestamp=1.0,
        interfaces=[
            NetworkInterfaceSnapshot(
                name="wlan0", rx_bytes=1, tx_bytes=1, rx_packets=1, tx_packets=1,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0,
            ),
            NetworkInterfaceSnapshot(
                name="ccmni5", rx_bytes=0, tx_bytes=0, rx_packets=0, tx_packets=0,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0,
            ),
            NetworkInterfaceSnapshot(
                name="lo", rx_bytes=0, tx_bytes=0, rx_packets=0, tx_packets=0,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0,
            ),
        ],
        aggregate_rx_bytes=1,
        aggregate_tx_bytes=1,
        interface_throughput={
            "wlan0": NetworkThroughput(rx_bytes_per_sec=5000.0, tx_bytes_per_sec=1000.0),
            "ccmni5": NetworkThroughput(rx_bytes_per_sec=0.0, tx_bytes_per_sec=0.0),
            "lo": NetworkThroughput(rx_bytes_per_sec=0.0, tx_bytes_per_sec=0.0),
        },
        aggregate_throughput=NetworkThroughput(rx_bytes_per_sec=5000.0, tx_bytes_per_sec=1000.0),
    )
    widget = NetworkWidget()
    widget.set_snapshot(snapshot)
    assert widget._toggle.text() == "Show all interfaces"
    widget.set_show_all(True)
    assert widget._toggle.text() == "Hide idle interfaces"
    rendered = _network_col0(widget)
    assert "ccmni5" in rendered
    assert "Loopback" in rendered
    assert "lo" in rendered


def test_network_widget_sorts_by_total_throughput_desc(qtapp) -> None:
    snapshot = NetworkSnapshot(
        timestamp=1.0,
        interfaces=[
            NetworkInterfaceSnapshot(
                name="ccmni3", rx_bytes=1, tx_bytes=1, rx_packets=1, tx_packets=1,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0,
            ),
            NetworkInterfaceSnapshot(
                name="ccmni11", rx_bytes=1, tx_bytes=1, rx_packets=1, tx_packets=1,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0,
            ),
        ],
        aggregate_rx_bytes=2,
        aggregate_tx_bytes=2,
        interface_throughput={
            "ccmni3": NetworkThroughput(rx_bytes_per_sec=5000.0, tx_bytes_per_sec=0.0),
            "ccmni11": NetworkThroughput(rx_bytes_per_sec=2000.0, tx_bytes_per_sec=0.0),
        },
        aggregate_throughput=NetworkThroughput(rx_bytes_per_sec=7000.0, tx_bytes_per_sec=0.0),
    )
    widget = NetworkWidget()
    widget.set_snapshot(snapshot)
    rendered = _network_col0(widget)
    assert rendered.index("ccmni3") < rendered.index("ccmni11")


def test_network_widget_empty_active_state(qtapp) -> None:
    snapshot = NetworkSnapshot(
        timestamp=1.0,
        interfaces=[
            NetworkInterfaceSnapshot(
                name="ccmni7", rx_bytes=0, tx_bytes=0, rx_packets=0, tx_packets=0,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0,
            ),
        ],
        aggregate_rx_bytes=0,
        aggregate_tx_bytes=0,
        interface_throughput={
            "ccmni7": NetworkThroughput(rx_bytes_per_sec=0.0, tx_bytes_per_sec=0.0),
        },
        aggregate_throughput=NetworkThroughput(rx_bytes_per_sec=0.0, tx_bytes_per_sec=0.0),
    )
    widget = NetworkWidget()
    widget.set_snapshot(snapshot)
    assert "No active network traffic" in _network_col0(widget)


def test_network_classifier_categories() -> None:
    assert classify_interface("wlan0") == "Wi-Fi"
    assert classify_interface("ccmni3") == "Mobile Data"
    assert classify_interface("rmnet_data0") == "Mobile Data"
    assert classify_interface("ppp0") == "Mobile Data"
    assert classify_interface("tun0") == "VPN/Tunnel"
    assert classify_interface("tap0") == "VPN/Tunnel"
    assert classify_interface("p2p0") == "Wi-Fi Direct"
    assert classify_interface("lo") == "Loopback"
    assert classify_interface("dummy0") == "Virtual"
    assert classify_interface("veth1") == "Virtual"


def test_network_classifier_unknown() -> None:
    # Unrecognized names must not raise; they fall back to Unknown.
    assert classify_interface("garbage7") == "Unknown"
    assert classify_interface("eth0") == "Unknown"
    assert classify_interface("") == "Unknown"


# ---------------------------------------------------------------------------
# Process inspection tests (selection -> worker -> detail panel)
# ---------------------------------------------------------------------------


def _inspector_responses() -> dict[str, str]:
    return {
        "cat /proc/24791/status": (
            "Name:\tcom.instagram.android\n"
            "State:\tS (sleeping)\n"
            "Uid:\t10203\t10203\t10203\t10203\n"
            "Threads:\t42\n"
            "VmSize:\t1842320 kB\n"
            "VmRSS:\t232448 kB\n"
            "RssAnon:\t216704 kB\n"
            "RssFile:\t14336 kB\n"
            "RssShmem:\t1408 kB\n"
        ),
        "cat /proc/24791/stat": (
            "24791 (com.instagram.android) S 754 754 0 0 -1 4194624 117531 0 144 0 "
            "316 355 152 552 11 0 42 256884 1842327561 1842327552 58112 "
            "18446744073709551615 0 0 0 0 0 0 0 2147483647 0 0 0 0 0 0 0 0 0 0 28 7 0 0 0 0 0"
        ),
        "cat /proc/24791/cmdline": "com.instagram.android\x00--fg",
        "cat /proc/24791/io": "read_bytes: 67890\nwrite_bytes: 54321\n",
    }


def test_process_selection_emits_inspection_request(qtapp) -> None:
    widget = ProcessWidget()
    requested: list[int] = []
    widget.inspection_requested.connect(requested.append)
    widget.set_snapshot(process_snapshot())
    widget._table.selectRow(0)
    assert requested == [8150]


def test_inspection_worker_returns_normalized_snapshot(qtapp) -> None:
    worker = ProcessInspectionWorker(connection=_FakeConnection(_inspector_responses()))
    snapshot = worker.inspect(24791)
    assert snapshot.pid == 24791
    assert snapshot.name == "com.instagram.android"
    assert snapshot.uid == 10203
    assert snapshot.threads == 42
    assert snapshot.priority == 11
    assert snapshot.command_line == "com.instagram.android --fg"
    assert snapshot.io_read_bytes == 67890


def test_inspection_worker_failure_emits_failed_signal(qtapp) -> None:
    worker = ProcessInspectionWorker(
        connection=_FakeConnection({}, fail=ADBDisconnectedError("device offline"))
    )
    failures: list[tuple] = []
    worker.inspection_failed.connect(lambda pid, msg: failures.append((pid, msg)))
    worker.request_inspect(24791)
    assert failures and failures[0][0] == 24791


def test_inspection_worker_rejects_bad_pid(qtapp) -> None:
    worker = ProcessInspectionWorker(connection=_FakeConnection({}))
    failures: list[tuple] = []
    worker.inspection_failed.connect(lambda pid, msg: failures.append((pid, msg)))
    worker.request_inspect("not-a-pid")
    assert failures and failures[0][0] == -1


def test_window_renders_inspection_snapshot_with_metrics(qtapp) -> None:
    window = MainWindow()
    window.update_snapshots(
        cpu_snapshot(), memory_snapshot(), process_snapshot(), battery_snapshot(), network_snapshot()
    )
    snapshot = ProcessInspectionSnapshot(
        pid=24791,
        name="com.instagram.android",
        uid=10203,
        state="S (sleeping)",
        threads=42,
        priority=11,
        nice=0,
        virtual_memory_kb=1842320,
        resident_memory_kb=232448,
        shared_memory_kb=1408,
        command_line="com.instagram.android --fg",
        io_read_bytes=67890,
        io_write_bytes=54321,
        timestamp=1.0,
    )
    window.on_inspection_ready(snapshot)
    panel = window.processes._inspector
    assert not panel.isHidden()
    assert panel._title.text() == "com.instagram.android"
    # cpu/memory percents come from the latest ProcessInfo for PID 24791 (2.9%).
    assert panel._rows["CPU"].text() == "2.9%"
    assert panel._rows["Memory"].text() == "5.5%"
    assert panel._rows["Resident"].text() == "227 MB"
    assert panel._rows["Virtual"].text() == "1.76 GB"
    assert panel._rows["Threads"].text() == "42"
    assert panel._rows["I/O Read"].text() == "67,890 B"
    assert "Command Line" in panel._command_line.text()


def test_inspection_io_unavailable_is_explicit_not_zero(qtapp) -> None:
    window = MainWindow()
    window.update_snapshots(
        cpu_snapshot(), memory_snapshot(), process_snapshot(), battery_snapshot(), network_snapshot()
    )
    window.on_inspection_ready(
        ProcessInspectionSnapshot(
            pid=8150, name="com.heavy.app", timestamp=1.0, io_read_bytes=None, io_write_bytes=None
        )
    )
    panel = window.processes._inspector
    # The device denied reading /proc/<pid>/io; the UI must say so explicitly
    # rather than fabricate a "0 B" counter, and the reason is one hover away.
    assert panel._rows["I/O Read"].text() == "Unavailable"
    assert panel._rows["I/O Write"].text() == "Unavailable"
    assert panel._rows["I/O Read"].toolTip() != ""
    assert panel._rows["I/O Write"].toolTip() == panel._rows["I/O Read"].toolTip()
    assert panel._rows["Shared"].property("mono") is True


def test_window_renders_process_gone_state(qtapp) -> None:
    window = MainWindow()
    window.update_snapshots(
        cpu_snapshot(), memory_snapshot(), process_snapshot(), battery_snapshot(), network_snapshot()
    )
    window.on_inspection_failed(24791, "adb command failed with exit code 1")
    panel = window.processes._inspector
    assert not panel.isHidden()
    assert panel._title.text() == "Process no longer available."
    assert "24791" in panel._subtitle.text()
    assert panel._rows["CPU"].text() == "N/A"


def test_wire_inspector_connects_full_loop(qtapp) -> None:
    window = MainWindow()
    inspector = ProcessInspectionWorker(connection=_FakeConnection(_inspector_responses()))
    wire_inspector(window, inspector)
    window.inspect_requested.emit(24791)
    panel = window.processes._inspector
    assert not panel.isHidden()
    assert panel._title.text() == "com.instagram.android"


def _investigation_snapshot() -> NetworkInvestigationSnapshot:
    return NetworkInvestigationSnapshot(
        timestamp=1.0,
        sockets=(
            SocketInfo(
                protocol="tcp",
                family="ipv6",
                local_address="2402:8100:39e1:2828:5a09:e8eb:ec1f:ab40",
                local_port=46006,
                remote_address="64:ff9b:0:0:0:0:9df0:1127",
                remote_port=443,
                state="CLOSE-WAIT",
                uid=10203,
                inode=30828972,
            ),
        ),
        source_available=True,
        uid_packages={10203: ("com.instagram.android",)},
    )


def test_window_renders_network_section_for_process_uid(qtapp) -> None:
    window = MainWindow()
    window.update_network_investigation(_investigation_snapshot())
    window.on_inspection_ready(
        ProcessInspectionSnapshot(pid=24791, name="com.instagram.android", uid=10203, timestamp=1.0)
    )
    panel = window.processes._inspector
    assert "10203" in panel._network_caption.text()
    assert "com.instagram.android" in panel._network_caption.text()
    assert panel._network_table.rowCount() == 1
    assert panel._network_table.item(0, 0).text() == "TCP IPV6"
    assert panel._network_table.item(0, 1).text() == "2402:8100:39e1:2828:5a09:e8eb:ec1f:ab40:46006"
    assert panel._network_table.item(0, 3).text() == "CLOSE-WAIT"


def test_inspector_network_section_states_are_distinct(qtapp) -> None:
    panel = _inspector_with_uid(10203)

    # (a) awaiting the first investigation sample.
    assert "Awaiting" in panel._network_caption.text()
    assert panel._network_table.rowCount() == 0

    # (b) device refused the socket reads: never fabricate, say so instead.
    panel.set_network_data(
        NetworkInvestigationSnapshot(
            timestamp=1.0, sockets=(),
            source_available=False, source_errors=("denied",),
        )
    )
    assert "unavailable" in panel._network_caption.text().lower()
    assert panel._network_table.rowCount() == 0

    # (c) tables read but the device held no sockets at all.
    panel.set_network_data(
        NetworkInvestigationSnapshot(timestamp=1.0, sockets=(), source_available=True)
    )
    assert "No connections were observed" in panel._network_caption.text()

    # (d) sockets exist, none attributed to this UID.
    panel.set_network_data(
        NetworkInvestigationSnapshot(
            timestamp=1.0,
            sockets=(
                SocketInfo(
                    protocol="tcp", family="ipv6",
                    local_address="2001:db8::1", local_port=53,
                    remote_address="2001:db8::2", remote_port=443,
                    state="ESTABLISHED", uid=1000, inode=1,
                ),
            ),
            source_available=True,
        )
    )
    assert "No connections attributed" in panel._network_caption.text()
    assert panel._network_table.rowCount() == 0


def _inspector_with_uid(uid: int):
    """Show a process panel so network-data updates re-render."""
    from android_task_manager.gui.widgets.process_inspector_widget import (
        ProcessInspectorWidget,
    )

    panel = ProcessInspectorWidget()
    panel.set_snapshot(
        ProcessInspectionSnapshot(pid=24791, name="com.instagram.android", uid=uid, timestamp=1.0)
    )
    return panel


def test_inspector_network_heals_as_samples_arrive(qtapp) -> None:
    panel = _inspector_with_uid(10203)
    assert "Awaiting" in panel._network_caption.text()
    panel.set_network_data(_investigation_snapshot())
    assert panel._network_table.rowCount() == 1
    assert "com.instagram.android" in panel._network_caption.text()


def test_worker_emits_network_investigation_signal(qtapp) -> None:
    worker = MonitorWorker(connection=_FakeConnection(_device_responses()))
    received: list = []
    worker.network_investigation.connect(received.append)
    worker._connect()
    worker.tick()
    assert len(received) == 1
    snapshot = received[0]
    assert isinstance(snapshot, NetworkInvestigationSnapshot)
    assert snapshot.source_available is True
    assert snapshot.packages_for_uid(10203) == ("com.instagram.android",)
    sockets = snapshot.sockets_for_uid(10203)
    assert len(sockets) == 1
    assert sockets[0].state == "CLOSE-WAIT"


def test_process_inspector_hide_button(qtapp) -> None:
    window = MainWindow()
    window.update_snapshots(
        cpu_snapshot(), memory_snapshot(), process_snapshot(), battery_snapshot(), network_snapshot()
    )
    window.on_inspection_ready(
        ProcessInspectionSnapshot(pid=8150, name="com.heavy.app", timestamp=1.0)
    )
    panel = window.processes._inspector
    assert not panel.isHidden()
    panel._hide.click()
    assert panel.isHidden()


def test_process_widget_excludes_monitor_top_process(qtapp) -> None:
    snapshot = ProcessSnapshot(
        timestamp=1.0,
        processes=[
            ProcessInfo(pid=14122, name="top -n 1", uid=0, state="R", cpu_percent=30.3, memory_percent=0.1, category="user"),
            ProcessInfo(pid=8150, name="com.heavy.app", uid=10001, state="R", cpu_percent=120.4, memory_percent=2.0, category="user"),
        ],
    )
    widget = ProcessWidget()
    widget.set_snapshot(snapshot)
    assert widget._table.rowCount() == 1
    assert widget._table.item(0, 0).text() == "8150"


def test_process_widget_keeps_similarly_named_processes(qtapp) -> None:
    snapshot = ProcessSnapshot(
        timestamp=1.0,
        processes=[
            ProcessInfo(pid=11, name="top", uid=0, state="S", cpu_percent=1.0, memory_percent=0.0, category="user"),
            ProcessInfo(pid=12, name="top -n 2", uid=0, state="S", cpu_percent=2.0, memory_percent=0.0, category="user"),
            ProcessInfo(pid=13, name="top_daemon", uid=0, state="S", cpu_percent=3.0, memory_percent=0.0, category="user"),
            ProcessInfo(pid=14, name="toybox top -n 1", uid=0, state="R", cpu_percent=9.0, memory_percent=0.0, category="user"),
        ],
    )
    widget = ProcessWidget()
    widget.set_snapshot(snapshot)
    assert widget._table.rowCount() == 3
    pids = {widget._table.item(row, 0).text() for row in range(widget._table.rowCount())}
    assert pids == {"11", "12", "13"}


def test_device_widget_states(qtapp) -> None:
    widget = DeviceWidget()
    widget.set_status(ConnectionState.CONNECTED, "")
    assert widget._status.text() == "\u25cf Connected"
    widget.set_status(ConnectionState.UNAUTHORIZED, "denied")
    assert widget._status.text() == "\u26a0 Not authorized"
    assert widget._status.toolTip() == "denied"


def test_main_window_receives_all_snapshots(qtapp) -> None:
    window = MainWindow()
    window.update_device("vivo V2026", "11")
    window.update_connection(ConnectionState.CONNECTED, "")
    window.update_snapshots(cpu_snapshot(), memory_snapshot(), process_snapshot(), battery_snapshot(), network_snapshot())
    assert window.device._title.text() == "vivo V2026"
    assert window.device._subtitle.text() == "Android 11"
    assert window.device._status.text() == "\u25cf Connected"
    assert window.cpu._overall.text() == "12.4%"
    assert window.memory._available.text() == "822 MB"
    assert window.battery._level.text() == "38%"
    assert window.processes._table.rowCount() == 3
    assert window.network._down.text() == "2.00 MB/s"


# ---------------------------------------------------------------------------
# Monitor worker tests (synchronous ticks, no real thread)
# ---------------------------------------------------------------------------


def test_worker_emits_snapshots_and_connected_state(qtapp) -> None:
    worker = MonitorWorker(connection=_FakeConnection(_device_responses()))
    received: dict = {}
    states: list = []

    worker.snapshots.connect(lambda *args: received.setdefault("snapshots", args))
    worker.device_info.connect(lambda label, version: received.setdefault("device", (label, version)))
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))

    worker._connect()
    worker.tick()
    worker.tick()

    cpu, memory, processes, battery, network = received["snapshots"]
    assert isinstance(cpu, CPUSnapshot)
    assert isinstance(memory, MemorySnapshot)
    assert isinstance(processes, ProcessSnapshot)
    assert isinstance(battery, BatterySnapshot)
    assert isinstance(network, NetworkSnapshot)
    assert processes.processes[0].pid == 100
    assert battery.level_percent == pytest.approx(38.0)
    assert received["device"] == ("vivo V2026", "11")
    assert ConnectionState.CONNECTED in {state for state, _ in states}


def test_worker_caches_failed_subsystems(qtapp) -> None:
    responses = _device_responses()
    # Break only the battery and network commands; CPU/memory/process still succeed.
    responses["dumpsys battery"] = ""
    responses["cat /proc/net/dev"] = ""
    worker = MonitorWorker(connection=_FakeConnection(responses))
    received: dict = {}
    states: list = []
    worker.snapshots.connect(lambda *args: received.setdefault("snapshots", args))
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))

    worker._connect()
    worker.tick()

    cpu, memory, processes, battery, network = received["snapshots"]
    assert isinstance(cpu, CPUSnapshot)
    assert isinstance(memory, MemorySnapshot)
    assert isinstance(processes, ProcessSnapshot)
    assert battery is None
    assert network is None
    assert ConnectionState.COLLECTOR_ERROR in {state for state, _ in states}


def test_worker_unauthorized_no_crash(qtapp) -> None:
    worker = MonitorWorker(
        connection=_FakeConnection({}, fail=ADBUnauthorizedError("not allowed"))
    )
    states: list = []
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))

    worker._connect()
    worker.tick()
    assert ConnectionState.UNAUTHORIZED in {state for state, _ in states}


def test_worker_timeout_no_crash(qtapp) -> None:
    worker = MonitorWorker(connection=_FakeConnection({}, fail=ADBTimeoutError("cat /proc/stat", 10.0)))
    states: list = []
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))
    worker.tick()
    assert ConnectionState.TIMEOUT in {state for state, _ in states}


def test_worker_no_device_no_crash(qtapp) -> None:
    worker = MonitorWorker(connection=_FakeConnection({}, fail=ADBNoDeviceError("none")))
    states: list = []
    emitted: list = []
    worker.connection_changed.connect(lambda state, detail: states.append((state, detail)))
    worker.snapshots.connect(lambda *args: emitted.append(args))
    worker.tick()
    assert ConnectionState.DISCONNECTED in {state for state, _ in states}
    assert emitted and emitted[0][0] is None


# ---------------------------------------------------------------------------
# Wiring + hygiene checks
# ---------------------------------------------------------------------------


def test_wire_and_worker_stop(qtapp) -> None:
    window = MainWindow()
    worker = MonitorWorker(connection=_FakeConnection(_device_responses()))
    wire(window, worker)
    assert not worker._stopped
    window.closed.emit()
    assert worker._stopped


def test_gui_widgets_do_not_import_subprocess_or_talk_to_adb() -> None:
    from android_task_manager.gui import widgets

    root = Path(widgets.__file__).resolve().parent
    for source in root.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "import subprocess" not in text
        assert "subprocess" not in text
        assert "shell(" not in text
        assert "adb.connection" not in text
        assert "Collector" not in text
        assert "ConnectionManager" not in text
        assert "parser" not in text


def test_monitor_delegates_instead_of_raw_shell() -> None:
    from android_task_manager.gui import monitor

    source = Path(monitor.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "ConnectionManager" in source  # owns the shared runner here only