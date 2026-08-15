"""Headless GUI tests for the Device page (offscreen Qt, no device needed).

Covers: page construction, summary rendering, every category card, honest
N/A handling, partial-data degradation, the disconnected empty state, and
the stale-data guarantee when the connected device changes. All data is
structured — the page is fed models, never raw ADB output.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel

from android_task_manager.battery.models import (
    BatteryHealth,
    BatterySnapshot,
    BatteryStatus,
)
from android_task_manager.cpu.models import CPUCore, CPUSnapshot
from android_task_manager.device.models import DeviceInformation, StorageInfo
from android_task_manager.gui.device_page import DevicePage
from android_task_manager.gui.main_window import MainWindow
from android_task_manager.gui.monitor import ConnectionState
from android_task_manager.gui.widgets.device_widget import DeviceWidget
from android_task_manager.memory.models import MemorySnapshot

from tests import device_fixtures as fx


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def device_info(scenario: str = "normal") -> DeviceInformation:
    runner = fx.DeviceRunner(fx.scenario(scenario))
    from android_task_manager.device import DeviceInfoCollector

    return DeviceInfoCollector(runner).sample()


def battery() -> BatterySnapshot:
    return BatterySnapshot(
        timestamp=1.0,
        level_percent=97.0,
        scale=100,
        voltage_mv=4376,
        temperature_c=33.5,
        status=BatteryStatus.CHARGING,
        status_raw=2,
        health=BatteryHealth.GOOD,
        health_raw=2,
        present=True,
        ac_powered=True,
        usb_powered=False,
        wireless_powered=False,
        technology="Li-poly",
        charge_counter=0,
    )


def memory() -> MemorySnapshot:
    return MemorySnapshot(
        timestamp=1.0,
        total_kb=2_865_476,
        free_kb=117_296,
        available_kb=842_000,
        buffers_kb=26_924,
        cached_kb=887_532,
        swap_cached_kb=0,
    )


def cpu() -> CPUSnapshot:
    return CPUSnapshot(
        timestamp=1.0,
        aggregate_utilization_percent=12.4,
        cores=[
            CPUCore(core_id=0, utilization_percent=12.0, frequency_khz=1_750_000, frequency_available=True),
            CPUCore(core_id=1, utilization_percent=13.0, frequency_khz=1_800_000, frequency_available=True),
        ],
    )


def make_page() -> DevicePage:
    return DevicePage(DeviceWidget())


def render_full(page: DevicePage) -> None:
    page.show()
    page.refresh(device_info(), battery(), memory(), cpu(), ConnectionState.CONNECTED)


def value_label(page: DevicePage, card: str, key: str) -> QLabel:
    return page._values[card][key]


# ---------------------------------------------------------------------------
# Construction & summary
# ---------------------------------------------------------------------------


def test_device_page_constructs(qtapp) -> None:
    page = make_page()
    assert page._device is not None
    page.show()
    assert page._empty.isVisible()  # nothing connected yet


def test_device_page_empty_state_shown_when_not_connected(qtapp) -> None:
    page = make_page()
    page.refresh(None, None, None, None, ConnectionState.DISCONNECTED)
    assert not page._empty.isHidden()
    assert "NO DEVICE CONNECTED" in page._empty.text()
    assert page._cards["BASIC INFORMATION"].isHidden()


def test_device_summary_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert "API 30" in page._summary_line.text()
    assert "Manufacturer vivo" in page._summary_line.text()
    assert "Brand vivo" in page._summary_line.text()
    # the existing DeviceWidget still drives the model/version/status line
    assert page._device._title.text() == "No device selected"
    page._device.set_info("vivo V2026", "11")
    assert page._device._subtitle.text() == "Android 11"


# ---------------------------------------------------------------------------
# Category cards
# ---------------------------------------------------------------------------


def test_basic_information_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "BASIC INFORMATION", "manufacturer").text() == "vivo"
    assert value_label(page, "BASIC INFORMATION", "model").text() == "V2026"
    assert value_label(page, "BASIC INFORMATION", "device").text() == "PD2026F"
    assert value_label(page, "BASIC INFORMATION", "product").text() == "PD2026F_EX_A"
    assert value_label(page, "BASIC INFORMATION", "board").text() == "kona"
    assert value_label(page, "BASIC INFORMATION", "hardware").text() == "qcom"
    assert value_label(page, "BASIC INFORMATION", "soc").text() == "Qualcomm SM8250"


def test_android_software_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "ANDROID / SOFTWARE", "android_version").text() == "11"
    assert value_label(page, "ANDROID / SOFTWARE", "api_level").text() == "30"
    assert value_label(page, "ANDROID / SOFTWARE", "security_patch").text() == "2021-06-01"
    assert value_label(page, "ANDROID / SOFTWARE", "build_id").text() == "RP1A.200720.012"
    assert value_label(page, "ANDROID / SOFTWARE", "bootloader").text() == "UFS"


def test_fingerprint_elided_but_full_value_in_tooltip(qtapp) -> None:
    page = make_page()
    render_full(page)
    label = value_label(page, "ANDROID / SOFTWARE", "fingerprint")
    assert label.text().endswith("\u2026")
    full = device_info().build_fingerprint
    assert label.toolTip() == full
    assert full.startswith(label.text()[:-1])


def test_hardware_cpu_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "CPU / HARDWARE", "processor").text() == "SM8250"
    assert value_label(page, "CPU / HARDWARE", "architecture").text() == "arm64-v8a"
    assert value_label(page, "CPU / HARDWARE", "cores").text() == "2"
    assert value_label(page, "CPU / HARDWARE", "max_frequency").text() == "2.84 GHz"
    assert value_label(page, "CPU / HARDWARE", "load").text() == "12.4%"


def test_battery_renders_from_live_snapshot(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "BATTERY", "level").text() == "97%"
    assert value_label(page, "BATTERY", "status").text() == "Charging"
    assert value_label(page, "BATTERY", "health").text() == "Good"
    assert value_label(page, "BATTERY", "temperature").text() == "33.5 \u00b0C"
    assert value_label(page, "BATTERY", "voltage").text() == "4.376 V"
    assert value_label(page, "BATTERY", "technology").text() == "Li-poly"


def test_memory_renders_from_live_snapshot(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "MEMORY", "ram_total").text() == "2.73 GB"
    assert value_label(page, "MEMORY", "ram_available").text() == "822 MB"
    assert value_label(page, "MEMORY", "ram_used").text() == "1.93 GB"


def test_storage_renders_with_usage_bar(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "STORAGE", "storage_total").text() == "116.29 GB"
    assert value_label(page, "STORAGE", "storage_used").text().startswith("65.92 GB")
    assert "(57%)" in value_label(page, "STORAGE", "storage_used").text()
    assert value_label(page, "STORAGE", "storage_free").text() == "50.37 GB"
    assert page._storage_bar is not None
    assert page._storage_bar.value() == 57
    assert page._storage_bar.isVisible()


def test_display_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "DISPLAY", "resolution").text() == "1080 \u00d7 2340"
    assert value_label(page, "DISPLAY", "density").text() == "440 dpi"
    assert value_label(page, "DISPLAY", "refresh_rate").text() == "60 Hz"
    assert value_label(page, "DISPLAY", "orientation").text() == "Portrait"


def test_identifiers_render(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "IDENTIFIERS", "android_id").text() == "a1b2c3d4e5f60718"
    assert value_label(page, "IDENTIFIERS", "wifi_mac").text() == "3c:28:6d:ab:cd:ef"
    assert value_label(page, "IDENTIFIERS", "bluetooth_mac").text() == "aa:bb:cc:dd:ee:ff"


# ---------------------------------------------------------------------------
# Honesty: N/A handling and partial data
# ---------------------------------------------------------------------------


def test_identifiers_unavailable_show_na(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("identifiers_unavailable"),
        battery(),
        memory(),
        cpu(),
        ConnectionState.CONNECTED,
    )
    assert value_label(page, "IDENTIFIERS", "android_id").text() == "N/A"
    assert value_label(page, "IDENTIFIERS", "wifi_mac").text() == "N/A"
    assert value_label(page, "IDENTIFIERS", "bluetooth_mac").text() == "N/A"


def test_partial_device_data_renders_without_crashing(qtapp) -> None:
    page = make_page()
    sparse = device_info("unknown_empty")  # model/version/build absent
    page.refresh(sparse, None, None, None, ConnectionState.CONNECTED)
    assert value_label(page, "BASIC INFORMATION", "manufacturer").text() == "vivo"
    assert value_label(page, "BASIC INFORMATION", "model").text() == "N/A"
    # Live-only cards collapse to the concise unavailable line.
    assert value_label(page, "BATTERY", "level").text() == "N/A"
    assert not page._na["BATTERY"].isHidden()
    assert "unavailable" in page._na["BATTERY"].text()


def test_category_with_no_data_collapses_to_concise_line(qtapp) -> None:
    page = make_page()
    info = device_info("normal")
    page.refresh(info, None, None, None, ConnectionState.CONNECTED)
    assert not page._na["BATTERY"].isHidden()
    assert page._na["BATTERY"].text() == "N/A — unavailable on this device"
    assert not page._na["MEMORY"].isHidden()


def test_render_resets_stale_values(qtapp) -> None:
    """Fields absent on a later render must not keep earlier values."""
    page = make_page()
    render_full(page)
    assert value_label(page, "ANDROID / SOFTWARE", "bootloader").text() == "UFS"
    page.refresh(
        device_info("missing_optional"), battery(), memory(), cpu(), ConnectionState.CONNECTED
    )
    assert value_label(page, "ANDROID / SOFTWARE", "bootloader").text() == "N/A"
    assert value_label(page, "BASIC INFORMATION", "soc").text() == "kona"


# ---------------------------------------------------------------------------
# Connection / device-change semantics
# ---------------------------------------------------------------------------


def test_disconnect_clears_page(qtapp) -> None:
    page = make_page()
    render_full(page)
    page.refresh(None, None, None, None, ConnectionState.DISCONNECTED)
    assert not page._empty.isHidden()
    assert page._cards["BASIC INFORMATION"].isHidden()
    assert page._summary_line.isHidden()


def test_device_switch_never_shows_stale_information(qtapp) -> None:
    page = make_page()
    first = device_info("normal")
    page.refresh(first, battery(), memory(), cpu(), ConnectionState.CONNECTED)
    assert value_label(page, "BASIC INFORMATION", "model").text() == "V2026"

    # Device A is unplugged: the page must empty out, not keep A's values.
    page.refresh(None, None, None, None, ConnectionState.DISCONNECTED)
    assert "V2026" not in value_label(page, "BASIC INFORMATION", "model").text()

    # Device B connects: only B's facts may appear.
    second = DeviceInformation(manufacturer="samsung", model="SM-G991B")
    page.refresh(second, battery(), memory(), cpu(), ConnectionState.CONNECTED)
    assert value_label(page, "BASIC INFORMATION", "model").text() == "SM-G991B"
    assert value_label(page, "BASIC INFORMATION", "manufacturer").text() == "samsung"
    assert "V2026" not in value_label(page, "BASIC INFORMATION", "model").text()


# ---------------------------------------------------------------------------
# MainWindow integration
# ---------------------------------------------------------------------------


def test_window_device_page_is_the_device_destination(qtapp) -> None:
    window = MainWindow()
    assert window._pages.widget(5).widget() is window.device_page
    assert window.device_page._device is window.device


def test_window_renders_structured_information(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "")
    window.update_device_information(device_info())
    window.update_snapshots(cpu(), memory(), None, battery(), None)
    page = window.device_page
    assert value_label(page, "BASIC INFORMATION", "manufacturer").text() == "vivo"
    assert value_label(page, "BATTERY", "level").text() == "97%"
    assert value_label(page, "MEMORY", "ram_total").text() == "2.73 GB"


def test_window_clears_information_on_disconnect(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "")
    window.update_device_information(device_info())
    assert window.device_information is not None
    window.update_connection(ConnectionState.DISCONNECTED, "gone")
    assert window.device_information is None
    assert not window.device_page._empty.isHidden()


def test_window_no_crash_when_collector_never_fired(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "")
    window.update_snapshots(cpu(), memory(), None, battery(), None)
    page = window.device_page
    assert value_label(page, "BASIC INFORMATION", "manufacturer").text() == "N/A"
    assert value_label(page, "BATTERY", "level").text() == "97%"