"""Truth-table tests for every diagnostics rule.

Each rule is verified for: normal, warning, critical (where applicable),
missing value, boundary value and contradictory evidence. The critical
invariant is exercised throughout: **UNKNOWN data must never produce a
finding that assumes a fact** — ``None`` / unreadable / ambiguous input
always yields an empty result.

Every emitted finding is verified field-by-field (severity, category,
title, what, why, evidence, recommended_action) so the structured
contract stays intact.
"""

from __future__ import annotations

import pytest

from android_task_manager.battery.models import (
    BatteryHealth,
    BatterySnapshot,
    BatteryStatus,
)
from android_task_manager.cpu.models import CPUSnapshot
from android_task_manager.device.models import DeviceInformation, StorageInfo
from android_task_manager.diagnostics.models import (
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticSeverity,
)
from android_task_manager.diagnostics.rules import (
    battery_charging,
    battery_health,
    battery_temperature,
    bootloader_lock,
    cpu_utilization,
    debuggable_build,
    memory_pressure,
    root_evidence,
    selinux_mode,
    storage_encryption,
    storage_utilization,
    verified_boot,
    verity_mode,
    wifi_without_address,
)
from android_task_manager.memory.models import MemorySnapshot


def _battery(**kwargs) -> BatterySnapshot:
    """A default battery snapshot; tests override the fields they target."""
    defaults = {
        "timestamp": 0.0,
        "level_percent": 50.0,
        "scale": 100,
        "voltage_mv": 3800,
        "temperature_c": 25.0,
        "status": BatteryStatus.NOT_CHARGING,
        "status_raw": 4,
        "health": BatteryHealth.GOOD,
        "health_raw": 2,
        "present": True,
        "ac_powered": None,
        "usb_powered": None,
        "wireless_powered": None,
        "technology": "Li-poly",
        "charge_counter": None,
    }
    defaults.update(kwargs)
    return BatterySnapshot(**defaults)


def _memory(**kwargs) -> MemorySnapshot:
    """A default memory snapshot; tests override the fields they target."""
    defaults = {
        "timestamp": 0.0,
        "total_kb": 4_000_000,
        "free_kb": 1_000_000,
        "available_kb": 2_000_000,
        "buffers_kb": 100_000,
        "cached_kb": 800_000,
        "swap_cached_kb": 0,
    }
    defaults.update(kwargs)
    return MemorySnapshot(**defaults)


def _cpu(utilization: float | None) -> CPUSnapshot:
    return CPUSnapshot(
        timestamp=0.0,
        aggregate_utilization_percent=utilization,
        cores=[],
    )


def _assert_finding(
    findings: tuple[DiagnosticFinding, ...],
    *,
    severity: DiagnosticSeverity,
    category: DiagnosticCategory,
    title: str,
) -> DiagnosticFinding:
    """Assert exactly one finding with the expected envelope, and that the
    explanation fields are all populated (never empty, never vague)."""
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity is severity
    assert finding.category is category
    assert finding.title == title
    assert finding.what
    assert finding.why
    assert finding.evidence
    assert finding.recommended_action
    return finding


# ---------------------------------------------------------------------------
# Battery: temperature
# ---------------------------------------------------------------------------


class TestBatteryTemperature:
    def test_normal_temperature_no_finding(self) -> None:
        assert battery_temperature(_battery(temperature_c=25.0)) == ()

    def test_missing_temperature_no_finding(self) -> None:
        assert battery_temperature(_battery(temperature_c=None)) == ()

    def test_elevated_boundary_is_normal(self) -> None:
        assert battery_temperature(_battery(temperature_c=40.0)) == ()

    def test_above_elevated_is_warning(self) -> None:
        finding = _assert_finding(
            battery_temperature(_battery(temperature_c=40.1)),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.BATTERY,
            title="Elevated battery temperature",
        )
        assert "40.1" in finding.evidence

    def test_just_below_critical_is_warning(self) -> None:
        assert battery_temperature(_battery(temperature_c=44.9))[0].severity is (
            DiagnosticSeverity.WARNING
        )

    def test_critical_boundary_is_critical(self) -> None:
        finding = _assert_finding(
            battery_temperature(_battery(temperature_c=45.0)),
            severity=DiagnosticSeverity.CRITICAL,
            category=DiagnosticCategory.BATTERY,
            title="Critical battery temperature",
        )
        assert "45.0" in finding.evidence

    def test_above_critical_is_critical(self) -> None:
        assert battery_temperature(_battery(temperature_c=50.0))[0].severity is (
            DiagnosticSeverity.CRITICAL
        )


# ---------------------------------------------------------------------------
# Battery: health
# ---------------------------------------------------------------------------


class TestBatteryHealth:
    def test_unknown_health_no_finding(self) -> None:
        assert battery_health(_battery(health=BatteryHealth.UNKNOWN)) == ()

    def test_good_health_no_finding(self) -> None:
        assert battery_health(_battery(health=BatteryHealth.GOOD)) == ()

    @pytest.mark.parametrize("health", [BatteryHealth.OVERHEAT, BatteryHealth.DEAD])
    def test_critical_health_states(self, health: BatteryHealth) -> None:
        finding = _assert_finding(
            battery_health(_battery(health=health)),
            severity=DiagnosticSeverity.CRITICAL,
            category=DiagnosticCategory.BATTERY,
            title="Battery reports overheat"
            if health is BatteryHealth.OVERHEAT
            else "Battery reports dead state",
        )
        assert health.label in finding.evidence

    @pytest.mark.parametrize(
        "health",
        [
            BatteryHealth.COLD,
            BatteryHealth.OVER_VOLTAGE,
            BatteryHealth.UNSPECIFIED_FAILURE,
        ],
    )
    def test_warning_health_states(self, health: BatteryHealth) -> None:
        finding = _assert_finding(
            battery_health(_battery(health=health)),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.BATTERY,
            title="Battery reports cold state"
            if health is BatteryHealth.COLD
            else "Battery reports over-voltage"
            if health is BatteryHealth.OVER_VOLTAGE
            else "Battery reports an unspecified failure",
        )
        assert health.label in finding.evidence


# ---------------------------------------------------------------------------
# Battery: charging
# ---------------------------------------------------------------------------


class TestBatteryCharging:
    def test_charging_no_finding(self) -> None:
        assert battery_charging(_battery(status=BatteryStatus.CHARGING)) == ()

    def test_not_charging_no_finding(self) -> None:
        assert battery_charging(_battery(status=BatteryStatus.NOT_CHARGING)) == ()

    def test_plain_discharge_is_informational(self) -> None:
        finding = _assert_finding(
            battery_charging(
                _battery(
                    status=BatteryStatus.DISCHARGING,
                    ac_powered=False,
                    usb_powered=False,
                    wireless_powered=False,
                )
            ),
            severity=DiagnosticSeverity.INFO,
            category=DiagnosticCategory.BATTERY,
            title="Battery is discharging",
        )
        assert "Discharging" in finding.evidence

    def test_unknown_power_flags_discharge_is_informational(self) -> None:
        """No power flag collected is NOT a power source: still INFO."""
        finding = battery_charging(_battery(status=BatteryStatus.DISCHARGING))
        assert len(finding) == 1
        assert finding[0].severity is DiagnosticSeverity.INFO

    def test_discharging_while_ac_powered_is_contradictory(self) -> None:
        finding = _assert_finding(
            battery_charging(
                _battery(status=BatteryStatus.DISCHARGING, ac_powered=True)
            ),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.BATTERY,
            title="Contradictory charging state reported",
        )
        assert "AC" in finding.evidence

    def test_discharging_while_usb_powered_is_contradictory(self) -> None:
        finding = battery_charging(
            _battery(status=BatteryStatus.DISCHARGING, usb_powered=True)
        )
        assert len(finding) == 1
        assert finding[0].severity is DiagnosticSeverity.WARNING
        assert "USB" in finding[0].evidence

    def test_discharging_while_wireless_powered_is_contradictory(self) -> None:
        finding = battery_charging(
            _battery(status=BatteryStatus.DISCHARGING, wireless_powered=True)
        )
        assert len(finding) == 1
        assert finding[0].severity is DiagnosticSeverity.WARNING
        assert "Wireless" in finding[0].evidence


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _device(storage: StorageInfo | None = None, **kwargs) -> DeviceInformation:
    return DeviceInformation(storage=storage, **kwargs)


class TestStorageUtilization:
    def test_no_storage_no_finding(self) -> None:
        assert storage_utilization(_device()) == ()

    def test_non_positive_total_no_finding(self) -> None:
        storage = StorageInfo(mount="/data", total_kb=0, used_kb=0, available_kb=0)
        assert storage_utilization(_device(storage)) == ()

    def test_normal_utilization_no_finding(self) -> None:
        storage = StorageInfo(
            mount="/data", total_kb=100_000, used_kb=50_000, available_kb=50_000
        )
        assert storage_utilization(_device(storage)) == ()

    def test_elevated_boundary_is_normal(self) -> None:
        storage = StorageInfo(
            mount="/data", total_kb=100_000, used_kb=80_000, available_kb=20_000
        )
        assert storage_utilization(_device(storage)) == ()

    def test_above_elevated_is_warning(self) -> None:
        storage = StorageInfo(
            mount="/data", total_kb=100_000, used_kb=85_000, available_kb=15_000
        )
        finding = _assert_finding(
            storage_utilization(_device(storage)),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.STORAGE,
            title="High storage utilization",
        )
        assert "/data" in finding.evidence
        assert "85%" in finding.evidence

    def test_critical_boundary_is_critical(self) -> None:
        storage = StorageInfo(
            mount="/data", total_kb=100_000, used_kb=90_000, available_kb=10_000
        )
        finding = _assert_finding(
            storage_utilization(_device(storage)),
            severity=DiagnosticSeverity.CRITICAL,
            category=DiagnosticCategory.STORAGE,
            title="Critical storage utilization",
        )
        assert "90%" in finding.evidence

    def test_above_critical_is_critical(self) -> None:
        storage = StorageInfo(
            mount="/data", total_kb=100_000, used_kb=95_000, available_kb=5_000
        )
        assert storage_utilization(_device(storage))[0].severity is (
            DiagnosticSeverity.CRITICAL
        )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class TestMemoryPressure:
    def test_normal_pressure_no_finding(self) -> None:
        assert memory_pressure(_memory()) == ()

    def test_non_positive_total_no_finding(self) -> None:
        assert memory_pressure(_memory(total_kb=0)) == ()

    def test_contradictory_negative_used_no_finding(self) -> None:
        """available > total is contradictory data: no claim is made."""
        assert memory_pressure(_memory(total_kb=100, available_kb=150)) == ()

    def test_elevated_boundary_is_normal(self) -> None:
        memory = _memory(total_kb=100_000, available_kb=30_000)
        assert memory_pressure(memory) == ()

    def test_above_elevated_is_warning(self) -> None:
        memory = _memory(total_kb=100_000, available_kb=25_000)
        finding = _assert_finding(
            memory_pressure(memory),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.MEMORY,
            title="High memory pressure",
        )
        assert "75%" in finding.evidence

    def test_critical_boundary_is_critical(self) -> None:
        memory = _memory(total_kb=100_000, available_kb=10_000)
        finding = _assert_finding(
            memory_pressure(memory),
            severity=DiagnosticSeverity.CRITICAL,
            category=DiagnosticCategory.MEMORY,
            title="Critical memory pressure",
        )
        assert "90%" in finding.evidence

    def test_above_critical_is_critical(self) -> None:
        memory = _memory(total_kb=100_000, available_kb=5_000)
        assert memory_pressure(memory)[0].severity is DiagnosticSeverity.CRITICAL


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------


class TestCpuUtilization:
    def test_missing_utilization_no_finding(self) -> None:
        """First sample (no delta baseline) must never produce a claim."""
        assert cpu_utilization(_cpu(None)) == ()

    def test_low_utilization_no_finding(self) -> None:
        assert cpu_utilization(_cpu(10.0)) == ()

    def test_elevated_boundary_is_normal(self) -> None:
        assert cpu_utilization(_cpu(60.0)) == ()

    def test_above_elevated_is_warning(self) -> None:
        finding = _assert_finding(
            cpu_utilization(_cpu(61.0)),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.CPU,
            title="High CPU utilization",
        )
        assert "61%" in finding.evidence

    def test_critical_boundary_is_critical(self) -> None:
        finding = _assert_finding(
            cpu_utilization(_cpu(85.0)),
            severity=DiagnosticSeverity.CRITICAL,
            category=DiagnosticCategory.CPU,
            title="Critical CPU utilization",
        )
        assert "85%" in finding.evidence

    def test_saturated_is_critical(self) -> None:
        assert cpu_utilization(_cpu(99.0))[0].severity is DiagnosticSeverity.CRITICAL


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


class TestWifiWithoutAddress:
    def test_wifi_state_unknown_no_finding(self) -> None:
        assert wifi_without_address(_device()) == ()

    def test_wifi_not_connected_no_finding(self) -> None:
        assert wifi_without_address(_device(wifi_connected=False)) == ()

    def test_address_sources_not_collected_no_finding(self) -> None:
        assert wifi_without_address(_device(wifi_connected=True)) == ()

    def test_partial_address_sources_no_finding(self) -> None:
        assert (
            wifi_without_address(
                _device(wifi_connected=True, ipv4_addresses=(), ipv6_addresses=None)
            )
            == ()
        )

    def test_connected_with_addresses_no_finding(self) -> None:
        assert (
            wifi_without_address(
                _device(
                    wifi_connected=True,
                    ipv4_addresses=("192.168.1.5",),
                    ipv6_addresses=(),
                )
            )
            == ()
        )

    def test_connected_without_any_address_is_warning(self) -> None:
        finding = _assert_finding(
            wifi_without_address(
                _device(wifi_connected=True, ipv4_addresses=(), ipv6_addresses=())
            ),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.NETWORK,
            title="Wi-Fi connected without an IP address",
        )
        assert "Connected" in finding.evidence


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class TestSelinuxMode:
    def test_unknown_mode_no_finding(self) -> None:
        assert selinux_mode(_device()) == ()

    def test_enforcing_no_finding(self) -> None:
        assert selinux_mode(_device(selinux_status="enforcing")) == ()

    def test_permissive_is_warning(self) -> None:
        finding = _assert_finding(
            selinux_mode(_device(selinux_status="permissive")),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="SELinux is in permissive mode",
        )
        assert "permissive" in finding.evidence

    def test_disabled_is_critical(self) -> None:
        finding = _assert_finding(
            selinux_mode(_device(selinux_status="disabled")),
            severity=DiagnosticSeverity.CRITICAL,
            category=DiagnosticCategory.SECURITY,
            title="SELinux is disabled",
        )
        assert "disabled" in finding.evidence

    def test_unrecognized_token_no_finding(self) -> None:
        assert selinux_mode(_device(selinux_status="mystery-mode")) == ()


class TestVerifiedBoot:
    def test_unknown_state_no_finding(self) -> None:
        assert verified_boot(_device()) == ()

    def test_green_no_finding(self) -> None:
        assert verified_boot(_device(verified_boot_state="green")) == ()

    @pytest.mark.parametrize("state", ["yellow", "orange"])
    def test_weakened_states_are_warnings(self, state: str) -> None:
        finding = _assert_finding(
            verified_boot(_device(verified_boot_state=state)),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="Verified Boot is not fully green",
        )
        assert state in finding.evidence

    def test_red_is_critical(self) -> None:
        finding = _assert_finding(
            verified_boot(_device(verified_boot_state="red")),
            severity=DiagnosticSeverity.CRITICAL,
            category=DiagnosticCategory.SECURITY,
            title="Verified Boot verification failed",
        )
        assert "red" in finding.evidence

    def test_unrecognized_token_no_finding(self) -> None:
        assert verified_boot(_device(verified_boot_state="purple")) == ()


class TestBootloaderLock:
    def test_unknown_state_no_finding(self) -> None:
        assert bootloader_lock(_device()) == ()

    def test_locked_no_finding(self) -> None:
        assert bootloader_lock(_device(bootloader_locked=True)) == ()

    def test_unlocked_is_warning(self) -> None:
        finding = _assert_finding(
            bootloader_lock(_device(bootloader_locked=False)),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="Bootloader is unlocked",
        )
        assert "unlocked" in finding.evidence


class TestRootEvidence:
    def test_unknown_no_finding(self) -> None:
        assert root_evidence(_device()) == ()

    def test_no_evidence_no_finding(self) -> None:
        """'no reliable root evidence found' is NOT a claim of anything."""
        assert root_evidence(_device(root_status="NO_ROOT_EVIDENCE")) == ()

    def test_root_evidence_is_warning(self) -> None:
        finding = _assert_finding(
            root_evidence(_device(root_status="ROOT_EVIDENCE")),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="Root evidence detected",
        )
        assert "detected" in finding.evidence


class TestDebuggableBuild:
    def test_unknown_no_finding(self) -> None:
        assert debuggable_build(_device()) == ()

    def test_non_debuggable_no_finding(self) -> None:
        assert debuggable_build(_device(debuggable=False)) == ()

    def test_debuggable_is_warning(self) -> None:
        finding = _assert_finding(
            debuggable_build(_device(debuggable=True)),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="Debuggable system build",
        )
        assert "debuggable" in finding.evidence


class TestStorageEncryption:
    def test_unknown_no_finding(self) -> None:
        assert storage_encryption(_device()) == ()

    def test_encrypted_no_finding(self) -> None:
        assert storage_encryption(_device(encryption_state="encrypted")) == ()

    def test_unencrypted_is_warning(self) -> None:
        finding = _assert_finding(
            storage_encryption(_device(encryption_state="unencrypted")),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="Storage encryption is disabled",
        )
        assert "unencrypted" in finding.evidence


class TestVerityMode:
    def test_unknown_no_finding(self) -> None:
        assert verity_mode(_device()) == ()

    def test_enforcing_no_finding(self) -> None:
        assert verity_mode(_device(verity_mode="enforcing")) == ()

    @pytest.mark.parametrize("mode", ["eio", "logging", "disabled"])
    def test_weakened_modes_are_warnings(self, mode: str) -> None:
        finding = _assert_finding(
            verity_mode(_device(verity_mode=mode)),
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="dm-verity integrity verification is weakened",
        )
        assert mode in finding.evidence

    def test_unrecognized_token_no_finding(self) -> None:
        assert verity_mode(_device(verity_mode="mystery")) == ()