"""Focused RED tests for Priority #8: device-supplied numeric validation.

Every test in this file encodes a concrete boundary that the current parser
or statistics layer does NOT enforce.  The tests MUST fail (RED) against the
current codebase; the production fix will flip them to GREEN.

Design rules (from the audit contract):
- Do NOT add arbitrary limits.  Every range is derived from Android/Linux
  semantics, an existing project invariant, or a documented physical
  constraint.
- Test public/parser behavior, not implementation details.
- No new product features; no version bumps; no commits.
"""

from __future__ import annotations

import pytest

# =========================================================================
# 1. MetricHistory: NaN and infinity must not poison rolling statistics
# =========================================================================


class TestMetricHistoryRejectsCorruptValues:
    """MetricHistory.add_sample must not accept NaN or ±inf.

    These values corrupt sums, averages, and trend calculations.  The
    contract is: only finite floats are recorded.
    """

    def test_nan_is_rejected(self) -> None:
        from android_task_manager.history.metrics import MetricHistory

        h = MetricHistory(max_samples=10)
        h.add_sample(50.0)
        h.add_sample(float("nan"))
        stats = h.stats()
        assert stats.count == 1
        assert stats.average == 50.0

    def test_positive_infinity_is_rejected(self) -> None:
        from android_task_manager.history.metrics import MetricHistory

        h = MetricHistory(max_samples=10)
        h.add_sample(10.0)
        h.add_sample(float("inf"))
        stats = h.stats()
        assert stats.count == 1
        assert stats.average == 10.0

    def test_negative_infinity_is_rejected(self) -> None:
        from android_task_manager.history.metrics import MetricHistory

        h = MetricHistory(max_samples=10)
        h.add_sample(20.0)
        h.add_sample(float("-inf"))
        stats = h.stats()
        assert stats.count == 1
        assert stats.average == 20.0


# =========================================================================
# 2. Process CPU/MEM%: negative and absurd values rejected
# =========================================================================


class TestProcessTopPercentageRange:
    """_parse_pct must reject negative and absurdly large values.

    Android ``top -n 1`` reports %MEM in 0-100; %CPU can exceed 100 on
    multi-core devices.  Negative values and values above 1000 indicate
    corrupted device output.
    """

    def test_negative_cpu_percent_is_rejected(self) -> None:
        from android_task_manager.process.parser import _parse_pct

        result = _parse_pct("-5.0")
        assert result is None

    def test_over_1000_cpu_percent_is_rejected(self) -> None:
        from android_task_manager.process.parser import _parse_pct

        result = _parse_pct("1500.0")
        assert result is None

    def test_multi_core_cpu_above_100_is_accepted(self) -> None:
        from android_task_manager.process.parser import _parse_pct

        assert _parse_pct("150.0") == 150.0

    def test_exact_0_is_accepted(self) -> None:
        from android_task_manager.process.parser import _parse_pct

        assert _parse_pct("0.0") == 0.0

    def test_exact_100_is_accepted(self) -> None:
        from android_task_manager.process.parser import _parse_pct

        assert _parse_pct("100.0") == 100.0

    def test_typical_value_is_accepted(self) -> None:
        from android_task_manager.process.parser import _parse_pct

        assert _parse_pct("23.7") == 23.7


# =========================================================================
# 3. Battery voltage: plausible millivolt range
# =========================================================================


class TestBatteryVoltageRange:
    """Battery voltage must be in a plausible millivolt range.

    Android batteries report voltage in millivolts.  Physical constraints:
    - Li-ion minimum ~2500 mV (deep discharge)
    - Li-ion maximum ~6000 mV (charger compliance)
    - Nominal range 3000-4200 mV
    """

    def test_negative_voltage_is_rejected(self) -> None:
        from android_task_manager.battery.parser import (
            BatteryParseError,
            parse_battery_output,
        )

        text = (
            "Current Battery Service state:\n"
            "  AC powered: false\n"
            "  USB powered: true\n"
            "  Wireless powered: false\n"
            "  status: 2\n"
            "  health: 2\n"
            "  present: true\n"
            "  level: 50\n"
            "  scale: 100\n"
            "  voltage: -500\n"
            "  temperature: 250\n"
            "  technology: Li-ion\n"
        )
        with pytest.raises(BatteryParseError):
            parse_battery_output(text)

    def test_zero_voltage_is_rejected(self) -> None:
        from android_task_manager.battery.parser import (
            BatteryParseError,
            parse_battery_output,
        )

        text = (
            "Current Battery Service state:\n"
            "  AC powered: false\n"
            "  USB powered: true\n"
            "  Wireless powered: false\n"
            "  status: 2\n"
            "  health: 2\n"
            "  present: true\n"
            "  level: 50\n"
            "  scale: 100\n"
            "  voltage: 0\n"
            "  temperature: 250\n"
            "  technology: Li-ion\n"
        )
        with pytest.raises(BatteryParseError):
            parse_battery_output(text)

    def test_absurdly_high_voltage_is_rejected(self) -> None:
        from android_task_manager.battery.parser import (
            BatteryParseError,
            parse_battery_output,
        )

        text = (
            "Current Battery Service state:\n"
            "  AC powered: false\n"
            "  USB powered: true\n"
            "  Wireless powered: false\n"
            "  status: 2\n"
            "  health: 2\n"
            "  present: true\n"
            "  level: 50\n"
            "  scale: 100\n"
            "  voltage: 99999\n"
            "  temperature: 250\n"
            "  technology: Li-ion\n"
        )
        with pytest.raises(BatteryParseError):
            parse_battery_output(text)

    def test_typical_voltage_is_accepted(self) -> None:
        from android_task_manager.battery.parser import parse_battery_output

        text = (
            "Current Battery Service state:\n"
            "  AC powered: false\n"
            "  USB powered: true\n"
            "  Wireless powered: false\n"
            "  status: 2\n"
            "  health: 2\n"
            "  present: true\n"
            "  level: 50\n"
            "  scale: 100\n"
            "  voltage: 3800\n"
            "  temperature: 250\n"
            "  technology: Li-ion\n"
        )
        snap = parse_battery_output(text)
        assert snap.voltage_mv == 3800


# =========================================================================
# 4. Battery temperature: plausible 0.1°C range
# =========================================================================


class TestBatteryTemperatureRange:
    """Battery temperature must be in a plausible 0.1°C range.

    Android reports temperature in tenths of a degree Celsius.
    Physical constraints:
    - Minimum plausible: -300 (-30°C, extreme cold)
    - Maximum plausible: 800 (80°C, thermal shutdown territory)
    """

    def test_extreme_high_temperature_is_rejected(self) -> None:
        from android_task_manager.battery.parser import (
            BatteryParseError,
            parse_battery_output,
        )

        text = (
            "Current Battery Service state:\n"
            "  AC powered: false\n"
            "  USB powered: true\n"
            "  Wireless powered: false\n"
            "  status: 2\n"
            "  health: 2\n"
            "  present: true\n"
            "  level: 50\n"
            "  scale: 100\n"
            "  voltage: 3800\n"
            "  temperature: 9999\n"
            "  technology: Li-ion\n"
        )
        with pytest.raises(BatteryParseError):
            parse_battery_output(text)

    def test_negative_extreme_temperature_is_rejected(self) -> None:
        from android_task_manager.battery.parser import (
            BatteryParseError,
            parse_battery_output,
        )

        text = (
            "Current Battery Service state:\n"
            "  AC powered: false\n"
            "  USB powered: true\n"
            "  Wireless powered: false\n"
            "  status: 2\n"
            "  health: 2\n"
            "  present: true\n"
            "  level: 50\n"
            "  scale: 100\n"
            "  voltage: 3800\n"
            "  temperature: -9999\n"
            "  technology: Li-ion\n"
        )
        with pytest.raises(BatteryParseError):
            parse_battery_output(text)

    def test_normal_temperature_is_accepted(self) -> None:
        from android_task_manager.battery.parser import parse_battery_output

        text = (
            "Current Battery Service state:\n"
            "  AC powered: false\n"
            "  USB powered: true\n"
            "  Wireless powered: false\n"
            "  status: 2\n"
            "  health: 2\n"
            "  present: true\n"
            "  level: 50\n"
            "  scale: 100\n"
            "  voltage: 3800\n"
            "  temperature: 250\n"
            "  technology: Li-ion\n"
        )
        snap = parse_battery_output(text)
        assert snap.temperature_c == 25.0


# =========================================================================
# 5. CPU tick counters: must be non-negative
# =========================================================================


class TestCPUCounterNonNegative:
    """CPU tick counters from /proc/stat must be non-negative.

    /proc/stat counters are unsigned 64-bit on Linux.  Negative values
    indicate corrupted output.
    """

    def test_negative_user_counter_is_rejected(self) -> None:
        from android_task_manager.cpu.parser import CPUParseError, parse_proc_stat

        text = "cpu  -100 200 300 400 50 10 5\n"
        with pytest.raises(CPUParseError):
            parse_proc_stat(text)

    def test_negative_idle_counter_is_rejected(self) -> None:
        from android_task_manager.cpu.parser import CPUParseError, parse_proc_stat

        text = "cpu  100 200 300 -400 50 10 5\n"
        with pytest.raises(CPUParseError):
            parse_proc_stat(text)

    def test_valid_counters_are_accepted(self) -> None:
        from android_task_manager.cpu.parser import parse_proc_stat

        text = "cpu  7412737 2342824 5072560 12345678 500000 10000 5000\n"
        snap = parse_proc_stat(text)
        assert snap.aggregate.user == 7412737
        assert snap.aggregate.idle == 12345678


# =========================================================================
# 6. Memory parser: negative values are invalid
# =========================================================================


class TestMemoryNonNegative:
    """Memory values from /proc/meminfo must be non-negative.

    /proc/meminfo reports unsigned integer KiB values.  Negative values
    indicate corrupted output.
    """

    def test_negative_total_is_rejected(self) -> None:
        from android_task_manager.memory.parser import MemoryParseError, parse_meminfo

        text = (
            "MemTotal:        -1000 kB\n"
            "MemFree:          500 kB\n"
            "MemAvailable:     800 kB\n"
            "Buffers:          100 kB\n"
            "Cached:           200 kB\n"
            "SwapCached:         0 kB\n"
        )
        with pytest.raises(MemoryParseError):
            parse_meminfo(text)

    def test_negative_available_is_rejected(self) -> None:
        from android_task_manager.memory.parser import MemoryParseError, parse_meminfo

        text = (
            "MemTotal:        1000 kB\n"
            "MemFree:          500 kB\n"
            "MemAvailable:    -800 kB\n"
            "Buffers:          100 kB\n"
            "Cached:           200 kB\n"
            "SwapCached:         0 kB\n"
        )
        with pytest.raises(MemoryParseError):
            parse_meminfo(text)


# =========================================================================
# 7. Storage: used_percent must be in [0, 100]
# =========================================================================


class TestStorageUsedPercentRange:
    """Storage used_percent must be clamped to [0, 100].

    If used_kb > total_kb (corrupted device output or snapshot timing),
    the percentage must not exceed 100%.
    """

    def test_used_percent_exceeds_100(self) -> None:
        from android_task_manager.storage.models import StorageSnapshot

        snap = StorageSnapshot(
            timestamp=0.0,
            mount="/data",
            total_kb=1000,
            used_kb=1500,
            available_kb=0,
        )
        assert snap.used_percent is not None
        assert snap.used_percent <= 100.0

    def test_zero_total_yields_none(self) -> None:
        from android_task_manager.storage.models import StorageSnapshot

        snap = StorageSnapshot(
            timestamp=0.0,
            mount="/data",
            total_kb=0,
            used_kb=0,
            available_kb=0,
        )
        assert snap.used_percent is None


# =========================================================================
# 8. Battery level_percent: must stay in [0, 100]
# =========================================================================


class TestBatteryLevelPercentRange:
    """Battery level_percent must be clamped to [0, 100].

    The parser already clamps, but this test verifies the contract holds
    even when level > scale (corrupted output).
    """

    def test_level_exceeding_scale_is_clamped(self) -> None:
        from android_task_manager.battery.parser import parse_battery_output

        text = (
            "Current Battery Service state:\n"
            "  AC powered: false\n"
            "  USB powered: true\n"
            "  Wireless powered: false\n"
            "  status: 2\n"
            "  health: 2\n"
            "  present: true\n"
            "  level: 150\n"
            "  scale: 100\n"
            "  voltage: 3800\n"
            "  temperature: 250\n"
            "  technology: Li-ion\n"
        )
        snap = parse_battery_output(text)
        assert snap.level_percent is not None
        assert snap.level_percent <= 100.0
        assert snap.level_percent >= 0.0
