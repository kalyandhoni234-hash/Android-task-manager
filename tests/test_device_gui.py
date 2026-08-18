"""Headless GUI tests for the Device page (offscreen Qt, no device needed).

Covers: page construction, summary rendering, every category card, honest
Unknown handling, partial-data degradation, the disconnected empty state,
the stale-data guarantee when the connected device changes, and the
Phase 2G sections (GPU, display, network, security) with their
unknown-state semantics. All data is structured — the page is fed models,
never raw ADB output.
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
from android_task_manager.device.models import DeviceInformation
from android_task_manager.gui.device_page import DevicePage, _format_duration
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


def battery_discharging() -> BatterySnapshot:
    return BatterySnapshot(
        timestamp=1.0,
        level_percent=40.0,
        scale=100,
        voltage_mv=3980,
        temperature_c=31.0,
        status=BatteryStatus.DISCHARGING,
        status_raw=3,
        health=BatteryHealth.GOOD,
        health_raw=2,
        present=True,
        ac_powered=False,
        usb_powered=False,
        wireless_powered=False,
        technology="Li-poly",
        charge_counter=0,
    )


def battery_unknown_source() -> BatterySnapshot:
    return BatterySnapshot(
        timestamp=1.0,
        level_percent=50.0,
        scale=100,
        voltage_mv=None,
        temperature_c=None,
        status=BatteryStatus.UNKNOWN,
        status_raw=1,
        health=BatteryHealth.UNKNOWN,
        health_raw=1,
        present=True,
        ac_powered=None,
        usb_powered=None,
        wireless_powered=None,
        technology="",
        charge_counter=None,
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
    assert page._cards["DEVICE"].isHidden()


def test_device_summary_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert "Model V2026" in page._summary_line.text()
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


def test_device_card_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "DEVICE", "manufacturer").text() == "vivo"
    assert value_label(page, "DEVICE", "model").text() == "V2026"
    assert value_label(page, "DEVICE", "device").text() == "PD2026F"
    assert value_label(page, "DEVICE", "product").text() == "PD2026F_EX_A"
    assert value_label(page, "DEVICE", "board").text() == "kona"
    assert value_label(page, "DEVICE", "hardware").text() == "qcom"
    assert value_label(page, "DEVICE", "soc").text() == "Qualcomm SM8250"


def test_system_android_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "SYSTEM / ANDROID", "android_version").text() == "11"
    assert value_label(page, "SYSTEM / ANDROID", "api_level").text() == "30"
    assert value_label(page, "SYSTEM / ANDROID", "build_id").text() == "RP1A.200720.012"
    assert value_label(page, "SYSTEM / ANDROID", "kernel").text() == "4.14.186+"
    assert value_label(page, "SYSTEM / ANDROID", "bootloader").text() == "UFS"
    assert value_label(page, "SYSTEM / ANDROID", "baseband").text() == (
        "MPSS.JO.4.7.c2-00125-8937_GEN_PACK-1.10"
    )


def test_fingerprint_elided_but_full_value_in_tooltip(qtapp) -> None:
    page = make_page()
    render_full(page)
    label = value_label(page, "SYSTEM / ANDROID", "fingerprint")
    assert label.text().endswith("\u2026")
    full = device_info().build_fingerprint
    assert label.toolTip() == full
    assert full.startswith(label.text()[:-1])


def test_processor_card_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "PROCESSOR", "processor").text() == "SM8250"
    assert value_label(page, "PROCESSOR", "architecture").text() == "arm64-v8a"
    assert value_label(page, "PROCESSOR", "cpu_64bit").text() == "Yes"
    assert value_label(page, "PROCESSOR", "cores").text() == "2"
    assert value_label(page, "PROCESSOR", "max_frequency").text() == "2.84 GHz"
    assert value_label(page, "PROCESSOR", "load").text() == "12.4%"


def test_battery_renders_from_live_snapshot(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "BATTERY", "level").text() == "97%"
    assert value_label(page, "BATTERY", "status").text() == "Charging"
    assert value_label(page, "BATTERY", "source").text() == "AC"
    assert value_label(page, "BATTERY", "health").text() == "Good"
    assert value_label(page, "BATTERY", "temperature").text() == "33.5 \u00b0C"
    assert value_label(page, "BATTERY", "voltage").text() == "4.376 V"
    assert value_label(page, "BATTERY", "technology").text() == "Li-poly"


def test_battery_discharging_source_is_battery(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info(), battery_discharging(), memory(), cpu(), ConnectionState.CONNECTED
    )
    assert value_label(page, "BATTERY", "status").text() == "Discharging"
    assert value_label(page, "BATTERY", "source").text() == "Battery"


def test_battery_source_unknown_when_not_reported(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info(), battery_unknown_source(), memory(), cpu(), ConnectionState.CONNECTED
    )
    assert value_label(page, "BATTERY", "source").text() == "Unknown"


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
    assert value_label(page, "STORAGE", "storage_mount").text() == "/data"
    assert value_label(page, "STORAGE", "storage_filesystem").text() == "ext4"
    assert page._storage_bar is not None
    assert page._storage_bar.value() == 57
    assert page._storage_bar.isVisible()


def test_display_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "GRAPHICS & DISPLAY", "resolution").text() == "1080 \u00d7 2340"
    assert value_label(page, "GRAPHICS & DISPLAY", "density").text() == "440 dpi"
    assert value_label(page, "GRAPHICS & DISPLAY", "refresh_rate").text() == "60 Hz"
    assert value_label(page, "GRAPHICS & DISPLAY", "orientation").text() == "Portrait"


def test_identifiers_render(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "IDENTIFIERS", "android_id").text() == "a1b2c3d4e5f60718"
    assert value_label(page, "IDENTIFIERS", "wifi_mac").text() == "3c:28:6d:ab:cd:ef"
    assert value_label(page, "IDENTIFIERS", "bluetooth_mac").text() == "aa:bb:cc:dd:ee:ff"


# ---------------------------------------------------------------------------
# Phase 2G: GPU & display details
# ---------------------------------------------------------------------------


def test_gpu_fields_render(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "GRAPHICS & DISPLAY", "gpu_vendor").text() == "Qualcomm"
    assert value_label(page, "GRAPHICS & DISPLAY", "gpu_model").text() == "Adreno (TM) 610"


def test_gpu_unknown_when_unavailable(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("gpu_unavailable"), battery(), memory(), cpu(), ConnectionState.CONNECTED
    )
    assert value_label(page, "GRAPHICS & DISPLAY", "gpu_vendor").text() == "Unknown"
    assert value_label(page, "GRAPHICS & DISPLAY", "gpu_model").text() == "Unknown"
    assert value_label(page, "GRAPHICS & DISPLAY", "resolution").text() == "1080 \u00d7 2340"


def test_supported_refresh_rates_render(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "GRAPHICS & DISPLAY", "supported_refresh_rates").text() == (
        "60 Hz \u00b7 90 Hz"
    )


def test_display_override_no_override_when_physical_readable(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "GRAPHICS & DISPLAY", "display_override").text() == "No override"


def test_display_override_reported_when_set(qtapp) -> None:
    page = make_page()
    info = DeviceInformation(
        manufacturer="vivo",
        model="V2026",
        resolution="1080x2340",
        display_override_resolution="720x1600",
        display_override_density=320,
    )
    page.refresh(info, None, None, None, ConnectionState.CONNECTED)
    assert value_label(page, "GRAPHICS & DISPLAY", "display_override").text() == (
        "720 \u00d7 1600 \u00b7 320 dpi"
    )


def test_display_override_unknown_when_display_unavailable(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("display_unavailable"), None, None, None, ConnectionState.CONNECTED
    )
    assert value_label(page, "GRAPHICS & DISPLAY", "display_override").text() == "Unknown"


# ---------------------------------------------------------------------------
# Phase 2G: system facts (uptime / boot time)
# ---------------------------------------------------------------------------


def test_uptime_and_boot_time_render(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "SYSTEM / ANDROID", "uptime").text() == "1d 10h"
    assert value_label(page, "SYSTEM / ANDROID", "boot_time").text().startswith(
        "2021-06-02 16:00"
    )


def test_duration_formatting() -> None:
    assert _format_duration(123456.78) == "1d 10h"
    assert _format_duration(3661) == "1h 1m"
    assert _format_duration(95) == "1m 35s"
    assert _format_duration(45) == "45s"
    assert _format_duration(0) == "0s"


# ---------------------------------------------------------------------------
# Phase 2G: battery static facts (design capacity / cycle count)
# ---------------------------------------------------------------------------


def test_battery_static_facts_render(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "BATTERY", "design_capacity").text() == "4,880,000 (reported)"
    assert value_label(page, "BATTERY", "cycle_count").text() == "412"


def test_battery_static_facts_unknown_when_absent(qtapp) -> None:
    page = make_page()
    page.refresh(
        DeviceInformation(manufacturer="vivo"),
        None,
        None,
        None,
        ConnectionState.CONNECTED,
    )
    assert value_label(page, "BATTERY", "design_capacity").text() == "Unknown"
    assert value_label(page, "BATTERY", "cycle_count").text() == "Unknown"


# ---------------------------------------------------------------------------
# Phase 2G: network
# ---------------------------------------------------------------------------


def test_network_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "NETWORK", "transport").text() == "Wi-Fi"
    assert value_label(page, "NETWORK", "wifi_enabled").text() == "Yes"
    assert value_label(page, "NETWORK", "wifi_connected").text() == "Connected"
    assert value_label(page, "NETWORK", "ssid").text() == "HomeWiFi"
    assert value_label(page, "NETWORK", "frequency").text() == "5180 MHz"
    assert value_label(page, "NETWORK", "link_speed").text() == "866 Mbps"
    assert value_label(page, "NETWORK", "rssi").text() == "-45 dBm"
    assert value_label(page, "NETWORK", "ipv4").text() == "192.168.50.10"
    assert value_label(page, "NETWORK", "ipv6").text() == "fe80::3c28:6dff:feab:cdef"
    assert value_label(page, "NETWORK", "gateway").text() == "192.168.50.1"
    assert value_label(page, "NETWORK", "dns").text() == "192.168.50.1, 9.9.9.9"
    assert value_label(page, "NETWORK", "vpn").text() == "Not detected"


def test_network_unavailable_renders_unknown(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("network_unavailable"),
        battery(),
        memory(),
        cpu(),
        ConnectionState.CONNECTED,
    )
    assert value_label(page, "NETWORK", "transport").text() == "Unknown"
    assert value_label(page, "NETWORK", "ssid").text() == "Unknown"
    assert value_label(page, "NETWORK", "vpn").text() == "Unknown"


def test_network_vpn_connected_with_interface(qtapp) -> None:
    page = make_page()
    info = DeviceInformation(
        manufacturer="vivo", model="V2026", vpn_active=True, vpn_interface="tun0"
    )
    page.refresh(info, None, None, None, ConnectionState.CONNECTED)
    assert value_label(page, "NETWORK", "vpn").text() == "Connected (tun0)"


# ---------------------------------------------------------------------------
# Phase 2G: security (evidence-based, unknown stays unknown)
# ---------------------------------------------------------------------------


def test_security_renders(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "SECURITY", "selinux").text() == "Enforcing"
    assert value_label(page, "SECURITY", "verified_boot").text() == "Green"
    assert value_label(page, "SECURITY", "bootloader_state").text() == "Locked"
    assert value_label(page, "SECURITY", "root").text() == "No root evidence detected"
    assert value_label(page, "SECURITY", "security_patch").text() == "2021-06-01"
    assert value_label(page, "SECURITY", "debuggable").text() == "No"
    assert value_label(page, "SECURITY", "secure_build").text() == "Yes"
    assert value_label(page, "SECURITY", "encryption").text() == "Encrypted"
    assert value_label(page, "SECURITY", "encryption_type").text() == "File"
    assert value_label(page, "SECURITY", "verity").text() == "Enforcing"


def test_security_unknown_is_unknown_not_false(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("security_unknown"),
        battery(),
        memory(),
        cpu(),
        ConnectionState.CONNECTED,
    )
    assert value_label(page, "SECURITY", "selinux").text() == "Unknown"
    assert value_label(page, "SECURITY", "verified_boot").text() == "Unknown"
    assert value_label(page, "SECURITY", "bootloader_state").text() == "Unknown"
    assert value_label(page, "SECURITY", "root").text() == "Unknown"
    assert value_label(page, "SECURITY", "security_patch").text() == "2021-06-01"
    assert value_label(page, "SECURITY", "debuggable").text() == "Unknown"
    assert value_label(page, "SECURITY", "secure_build").text() == "Unknown"
    assert value_label(page, "SECURITY", "encryption").text() == "Unknown"
    assert value_label(page, "SECURITY", "encryption_type").text() == "Unknown"
    assert value_label(page, "SECURITY", "verity").text() == "Unknown"


def test_root_unknown_never_renders_as_not_rooted(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("security_unknown"), None, None, None, ConnectionState.CONNECTED
    )
    text = value_label(page, "SECURITY", "root").text()
    assert text == "Unknown"
    assert "Not rooted" not in text
    assert "root evidence" not in text.lower()


def test_verified_boot_unknown_never_renders_as_secure(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("security_unknown"), None, None, None, ConnectionState.CONNECTED
    )
    text = value_label(page, "SECURITY", "verified_boot").text()
    assert text == "Unknown"
    assert "Secure" not in text
    assert "Green" not in text


def test_selinux_unknown_never_renders_as_disabled(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("security_unknown"), None, None, None, ConnectionState.CONNECTED
    )
    text = value_label(page, "SECURITY", "selinux").text()
    assert text == "Unknown"
    assert "Disabled" not in text


def test_root_evidence_detected_renders(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("security_root_evidence"),
        None,
        None,
        None,
        ConnectionState.CONNECTED,
    )
    assert value_label(page, "SECURITY", "root").text() == "Root evidence detected"


def test_security_unlocked_build_renders(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("security_unlocked"), None, None, None, ConnectionState.CONNECTED
    )
    assert value_label(page, "SECURITY", "verified_boot").text() == "Orange"
    assert value_label(page, "SECURITY", "bootloader_state").text() == "Unlocked"
    assert value_label(page, "SECURITY", "debuggable").text() == "Yes"
    assert value_label(page, "SECURITY", "secure_build").text() == "No"


def test_security_patch_renders_validated_date(qtapp) -> None:
    page = make_page()
    render_full(page)
    assert value_label(page, "SECURITY", "security_patch").text() == "2021-06-01"


# ---------------------------------------------------------------------------
# Honesty: Unknown handling and partial data
# ---------------------------------------------------------------------------


def test_identifiers_unavailable_show_unknown(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("identifiers_unavailable"),
        battery(),
        memory(),
        cpu(),
        ConnectionState.CONNECTED,
    )
    assert value_label(page, "IDENTIFIERS", "android_id").text() == "Unknown"
    assert value_label(page, "IDENTIFIERS", "wifi_mac").text() == "Unknown"
    assert value_label(page, "IDENTIFIERS", "bluetooth_mac").text() == "Unknown"


def test_partial_device_data_renders_without_crashing(qtapp) -> None:
    page = make_page()
    sparse = device_info("unknown_empty")  # model/version/build absent
    page.refresh(sparse, None, None, None, ConnectionState.CONNECTED)
    assert value_label(page, "DEVICE", "manufacturer").text() == "vivo"
    assert value_label(page, "DEVICE", "model").text() == "Unknown"
    # Battery keeps its static facts (design capacity) even without the
    # live snapshot; the live-only fields are Unknown, never stale.
    assert value_label(page, "BATTERY", "level").text() == "Unknown"
    assert value_label(page, "BATTERY", "design_capacity").text() == "4,880,000 (reported)"


def test_no_none_null_or_na_leaks_into_visible_ui(qtapp) -> None:
    page = make_page()
    page.refresh(
        device_info("unknown_empty"), None, None, None, ConnectionState.CONNECTED
    )
    for card, labels in page._values.items():
        for key, label in labels.items():
            assert "None" not in label.text(), (card, key, label.text())
            assert "null" not in label.text(), (card, key, label.text())
            assert "N/A" not in label.text(), (card, key, label.text())
            assert label.text() != "0", (card, key, label.text())
    for card, na in page._na.items():
        assert "N/A" not in na.text(), (card, na.text())


def test_category_with_no_data_collapses_to_concise_line(qtapp) -> None:
    page = make_page()
    page.refresh(DeviceInformation(), None, None, None, ConnectionState.CONNECTED)
    assert not page._na["BATTERY"].isHidden()
    assert page._na["BATTERY"].text() == "Not available on this device"
    assert not page._na["MEMORY"].isHidden()
    assert not page._na["NETWORK"].isHidden()
    assert not page._na["SECURITY"].isHidden()


def test_render_resets_stale_values(qtapp) -> None:
    """Fields absent on a later render must not keep earlier values."""
    page = make_page()
    render_full(page)
    assert value_label(page, "SYSTEM / ANDROID", "bootloader").text() == "UFS"
    page.refresh(
        device_info("missing_optional"),
        battery(),
        memory(),
        cpu(),
        ConnectionState.CONNECTED,
    )
    assert value_label(page, "SYSTEM / ANDROID", "bootloader").text() == "Unknown"
    assert value_label(page, "DEVICE", "soc").text() == "kona"


# ---------------------------------------------------------------------------
# Connection / device-change semantics
# ---------------------------------------------------------------------------


def test_disconnect_clears_page(qtapp) -> None:
    page = make_page()
    render_full(page)
    page.refresh(None, None, None, None, ConnectionState.DISCONNECTED)
    assert not page._empty.isHidden()
    assert page._cards["DEVICE"].isHidden()
    assert page._summary_line.isHidden()


def test_device_switch_never_shows_stale_information(qtapp) -> None:
    page = make_page()
    first = device_info("normal")
    page.refresh(first, battery(), memory(), cpu(), ConnectionState.CONNECTED)
    assert value_label(page, "DEVICE", "model").text() == "V2026"

    # Device A is unplugged: the page must empty out, not keep A's values.
    page.refresh(None, None, None, None, ConnectionState.DISCONNECTED)
    assert "V2026" not in value_label(page, "DEVICE", "model").text()

    # Device B connects: only B's facts may appear.
    second = DeviceInformation(manufacturer="samsung", model="SM-G991B")
    page.refresh(second, battery(), memory(), cpu(), ConnectionState.CONNECTED)
    assert value_label(page, "DEVICE", "model").text() == "SM-G991B"
    assert value_label(page, "DEVICE", "manufacturer").text() == "samsung"
    assert "V2026" not in value_label(page, "DEVICE", "model").text()


# ---------------------------------------------------------------------------
# MainWindow integration
# ---------------------------------------------------------------------------


def test_window_device_page_is_the_device_destination(qtapp) -> None:
    window = MainWindow()
    assert window._pages.widget(6).widget() is window.device_page
    assert window.device_page._device is window.device


def test_window_renders_structured_information(qtapp) -> None:
    window = MainWindow()
    window.update_connection(ConnectionState.CONNECTED, "")
    window.update_device_information(device_info())
    window.update_snapshots(cpu(), memory(), None, battery(), None)
    page = window.device_page
    assert value_label(page, "DEVICE", "manufacturer").text() == "vivo"
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
    assert value_label(page, "DEVICE", "manufacturer").text() == "Unknown"
    assert value_label(page, "BATTERY", "level").text() == "97%"