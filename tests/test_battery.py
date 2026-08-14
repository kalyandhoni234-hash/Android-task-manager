"""Unit tests for battery parsing, enum normalization and the collector.

Fixtures are based on the verified Vivo V2026 ``dumpsys battery`` output.
No device is required.
"""

from __future__ import annotations

import inspect

import pytest

from android_task_manager.adb.exceptions import ADBTimeoutError
from android_task_manager.battery.collector import BatteryCollector
from android_task_manager.battery.models import (
    BatteryHealth,
    BatterySnapshot,
    BatteryStatus,
    battery_health_from_raw,
    battery_status_from_raw,
)
from android_task_manager.battery.parser import BatteryParseError, parse_battery_output
from android_task_manager.terminal.renderer import _battery_lines

# Verified Vivo V2026 dumpsys battery fixture.
FIXTURE = """Current Battery Service state:
  AC powered: false
  USB powered: true
  Wireless powered: false
  Max charging current: 0
  Max charging voltage: 0
  Charge counter: -80000
  engine: 0
  soc decimal: 0
  board temp status: 0
  status: 2
  health: 2
  present: true
  level: 38
  scale: 100
  voltage: 4116
  temperature: 341
  technology: Li-poly
"""


def test_parse_real_vivo_fixture() -> None:
    snap = parse_battery_output(FIXTURE)
    assert snap.level_percent == pytest.approx(38.0)
    assert snap.scale == 100
    assert snap.voltage_mv == 4116
    assert snap.temperature_c == pytest.approx(34.1)
    assert snap.status is BatteryStatus.CHARGING
    assert snap.status_raw == 2
    assert snap.health is BatteryHealth.GOOD
    assert snap.health_raw == 2
    assert snap.present is True
    assert snap.ac_powered is False
    assert snap.usb_powered is True
    assert snap.wireless_powered is False
    assert snap.technology == "Li-poly"
    assert snap.charge_counter == -80000


def test_parse_discharging_fixture() -> None:
    discharging = """Current Battery Service state:
  AC powered: false
  USB powered: false
  Wireless powered: false
  Max charging current: 0
  Max charging voltage: 0
  Charge counter: -80000
  engine: 0
  soc decimal: 0
  board temp status: 0
  status: 3
  health: 2
  present: true
  level: 61
  scale: 100
  voltage: 3845
  temperature: 302
  technology: Li-poly
"""
    snap = parse_battery_output(discharging)
    assert snap.status is BatteryStatus.DISCHARGING
    assert snap.ac_powered is False
    assert snap.usb_powered is False
    assert snap.wireless_powered is False
    assert snap.present is True
    assert snap.level_percent == pytest.approx(61.0)
    assert snap.voltage_mv == 3845
    assert snap.temperature_c == pytest.approx(30.2)
    assert snap.health is BatteryHealth.GOOD
    assert snap.charge_counter == -80000


def test_field_order_independence() -> None:
    lines = [line for line in FIXTURE.splitlines() if ":" in line]
    reordered = "\n".join(reversed(lines)) + "\n"
    assert parse_battery_output(reordered) == parse_battery_output(FIXTURE)


def test_unknown_fields_tolerated() -> None:
    snap = parse_battery_output(FIXTURE)
    extra = FIXTURE + "FutureVendorField: 42\nSomeOemFlag: true\n"
    extra_snap = parse_battery_output(extra)
    assert extra_snap.level_percent == snap.level_percent
    assert extra_snap.status is BatteryStatus.CHARGING


def test_missing_required_field_raises() -> None:
    without_level = FIXTURE.replace("  level: 38\n", "")
    with pytest.raises(BatteryParseError):
        parse_battery_output(without_level)


def test_malformed_integer_raises() -> None:
    bad = FIXTURE.replace("  level: 38", "  level: thirty-eight")
    with pytest.raises(BatteryParseError):
        parse_battery_output(bad)


def test_malformed_boolean_raises() -> None:
    bad = FIXTURE.replace("  USB powered: true", "  USB powered: maybe")
    with pytest.raises(BatteryParseError):
        parse_battery_output(bad)


def test_level_scale_calculation() -> None:
    text = FIXTURE.replace("  scale: 100", "  scale: 200").replace("  level: 38", "  level: 50")
    snap = parse_battery_output(text)
    assert snap.level_percent == pytest.approx(25.0)


def test_invalid_scale_yields_unknown_level() -> None:
    text = FIXTURE.replace("  scale: 100", "  scale: 0")
    snap = parse_battery_output(text)
    assert snap.level_percent is None
    assert snap.status is BatteryStatus.CHARGING  # rest still parses fine


def test_level_clamped_to_valid_range() -> None:
    text = FIXTURE.replace("  level: 38", "  level: 250")
    snap = parse_battery_output(text)
    assert snap.level_percent == pytest.approx(100.0)


def test_temperature_conversion() -> None:
    assert parse_battery_output(FIXTURE).temperature_c == pytest.approx(34.1)


def test_voltage_parsed_as_millivolts() -> None:
    snap = parse_battery_output(FIXTURE)
    assert snap.voltage_mv == 4116


def test_status_enum_mapping() -> None:
    assert battery_status_from_raw(1) is BatteryStatus.UNKNOWN
    assert battery_status_from_raw(2) is BatteryStatus.CHARGING
    assert battery_status_from_raw(3) is BatteryStatus.DISCHARGING
    assert battery_status_from_raw(4) is BatteryStatus.NOT_CHARGING
    assert battery_status_from_raw(5) is BatteryStatus.FULL


def test_health_enum_mapping() -> None:
    assert battery_health_from_raw(1) is BatteryHealth.UNKNOWN
    assert battery_health_from_raw(2) is BatteryHealth.GOOD
    assert battery_health_from_raw(3) is BatteryHealth.OVERHEAT
    assert battery_health_from_raw(4) is BatteryHealth.DEAD
    assert battery_health_from_raw(5) is BatteryHealth.OVER_VOLTAGE
    assert battery_health_from_raw(6) is BatteryHealth.UNSPECIFIED_FAILURE
    assert battery_health_from_raw(7) is BatteryHealth.COLD


def test_unknown_enum_values_preserve_raw() -> None:
    text = FIXTURE.replace("  status: 2", "  status: 99").replace("  health: 2", "  health: 77")
    snap = parse_battery_output(text)
    assert snap.status is BatteryStatus.UNKNOWN
    assert snap.status_raw == 99
    assert snap.health is BatteryHealth.UNKNOWN
    assert snap.health_raw == 77


def test_power_source_combinations() -> None:
    usb_only = parse_battery_output(FIXTURE)
    assert usb_only.ac_powered is False
    assert usb_only.usb_powered is True
    assert usb_only.wireless_powered is False

    ac_and_wireless = FIXTURE.replace(
        "  AC powered: false\n", "  AC powered: true\n"
    ).replace("  USB powered: true\n", "  USB powered: false\n").replace(
        "  Wireless powered: false\n", "  Wireless powered: true\n"
    )
    snap = parse_battery_output(ac_and_wireless)
    assert snap.ac_powered is True
    assert snap.usb_powered is False
    assert snap.wireless_powered is True


def test_optional_charge_counter_malformed_tolerated() -> None:
    text = FIXTURE.replace("  Charge counter: -80000", "  Charge counter: n/a")
    snap = parse_battery_output(text)
    assert snap.charge_counter is None
    assert snap.level_percent == pytest.approx(38.0)


class _FakeRunner:
    """Serves a fixed dumpsys battery blob and records commands issued."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[list[str]] = []

    def shell(self, args, timeout=None):
        self.calls.append(list(args))
        return self.output


def test_collector_uses_command_runner() -> None:
    runner = _FakeRunner(FIXTURE)
    snap = BatteryCollector(runner).sample()
    assert isinstance(snap, BatterySnapshot)
    assert runner.calls == [["dumpsys", "battery"]]
    assert snap.timestamp >= 0.0


def test_collector_propagates_adb_failures() -> None:
    class _FailingRunner:
        def shell(self, args, timeout=None):
            raise ADBTimeoutError("dumpsys battery", 10.0)

    with pytest.raises(ADBTimeoutError):
        BatteryCollector(_FailingRunner()).sample()


def test_collector_does_not_import_subprocess() -> None:
    source = inspect.getsource(BatteryCollector)
    assert "subprocess" not in source


def test_renderer_formats_battery_section() -> None:
    snap = parse_battery_output(FIXTURE)
    text = "\n".join(_battery_lines(snap))
    assert "Level:        38%" in text
    assert "Status:       Charging" in text
    assert "Health:       Good" in text
    assert "Temperature:  34.1 \u00b0C" in text
    assert "Voltage:      4.116 V" in text
    assert "Technology:   Li-poly" in text
    assert "Power:        USB" in text


def test_renderer_hides_raw_enum_numbers() -> None:
    snap = parse_battery_output(FIXTURE)
    text = "\n".join(_battery_lines(snap))
    assert "status: 2" not in text
    assert "health: 2" not in text


def test_renderer_unknown_enum_and_missing_level() -> None:
    text = FIXTURE.replace("  status: 2", "  status: 9").replace("  level: 38", "  level: 250")
    snap = parse_battery_output(text)
    rendered = "\n".join(_battery_lines(snap))
    assert "Status:       Unknown" in rendered
    assert "Level:        100%" in rendered


def test_renderer_no_power_source_shows_none() -> None:
    text = FIXTURE.replace("  USB powered: true", "  USB powered: false")
    snap = parse_battery_output(text)
    rendered = "\n".join(_battery_lines(snap))
    assert "Power:        None" in rendered