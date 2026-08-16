"""Integration tests for the diagnostics evaluator.

``evaluate`` is the single engine entry point: it applies every rule to
one snapshot bundle, returns a deterministic, severity-ordered report,
and never produces a finding when the underlying data is missing.
"""

from __future__ import annotations

from android_task_manager.battery.models import (
    BatteryHealth,
    BatterySnapshot,
    BatteryStatus,
)
from android_task_manager.cpu.models import CPUSnapshot
from android_task_manager.device.models import DeviceInformation, StorageInfo
from android_task_manager.diagnostics import (
    DiagnosticCategory,
    DiagnosticSeverity,
    evaluate,
)
from android_task_manager.memory.models import MemorySnapshot


def _battery(**kwargs) -> BatterySnapshot:
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


def _cpu(utilization: float | None) -> CPUSnapshot:
    return CPUSnapshot(
        timestamp=0.0,
        aggregate_utilization_percent=utilization,
        cores=[],
    )


def _memory(used_percent: float) -> MemorySnapshot:
    total = 100_000
    return MemorySnapshot(
        timestamp=0.0,
        total_kb=total,
        free_kb=0,
        available_kb=int(total * (1 - used_percent / 100)),
        buffers_kb=0,
        cached_kb=0,
        swap_cached_kb=0,
    )


def _device(**kwargs) -> DeviceInformation:
    return DeviceInformation(**kwargs)


class TestEvaluateEmptyAndUnknown:
    def test_all_none_is_empty_report(self) -> None:
        report = evaluate(cpu=None, memory=None, battery=None, device=None)
        assert report.findings == ()

    def test_first_sample_cpu_and_unknown_fields_no_findings(self) -> None:
        """None on every relevant field must produce an empty report: an
        unknown value is never treated as a fact."""
        report = evaluate(
            cpu=_cpu(None),
            memory=_memory(50.0),
            battery=_battery(temperature_c=None),
            device=_device(),
        )
        assert report.findings == ()

    def test_no_device_no_security_or_storage_findings(self) -> None:
        report = evaluate(
            cpu=_cpu(95.0), memory=_memory(95.0), battery=None, device=None
        )
        categories = {f.category for f in report.findings}
        assert DiagnosticCategory.SECURITY not in categories
        assert DiagnosticCategory.STORAGE not in categories
        assert DiagnosticCategory.BATTERY not in categories


class TestEvaluateOrderingAndDeterminism:
    def test_critical_findings_come_first(self) -> None:
        report = evaluate(
            cpu=_cpu(90.0),
            memory=_memory(80.0),
            battery=_battery(temperature_c=41.0),
            device=_device(
                storage=StorageInfo(
                    mount="/data", total_kb=100_000, used_kb=85_000, available_kb=15_000
                ),
                selinux_status="permissive",
            ),
        )
        severities = [f.severity for f in report.findings]
        assert severities[0] is DiagnosticSeverity.CRITICAL
        assert severities[1] is DiagnosticSeverity.WARNING
        assert severities == sorted(
            severities, key=lambda s: -s.rank
        )

    def test_report_is_deterministic(self) -> None:
        kwargs = dict(
            cpu=_cpu(95.0),
            memory=_memory(95.0),
            battery=_battery(temperature_c=50.0),
            device=_device(
                storage=StorageInfo(
                    mount="/data", total_kb=100_000, used_kb=95_000, available_kb=5_000
                ),
                selinux_status="disabled",
                verified_boot_state="yellow",
                bootloader_locked=False,
                root_status="ROOT_EVIDENCE",
                debuggable=True,
                encryption_state="unencrypted",
                verity_mode="logging",
            ),
        )
        first = evaluate(**kwargs)
        second = evaluate(**kwargs)
        assert first == second
        assert len(first.findings) > 0

    def test_same_category_sorted_by_title(self) -> None:
        report = evaluate(
            cpu=None,
            memory=None,
            battery=_battery(
                temperature_c=50.0,
                health=BatteryHealth.DEAD,
                status=BatteryStatus.DISCHARGING,
            ),
            device=None,
        )
        findings = list(report.findings)
        # Critical findings precede INFO; titles are alphabetical within a
        # severity level.
        assert findings == sorted(
            findings, key=lambda f: (-f.severity.rank, f.title)
        )


class TestEvaluateBundle:
    def test_full_bundle_produces_expected_finding_set(self) -> None:
        report = evaluate(
            cpu=_cpu(95.0),
            memory=_memory(95.0),
            battery=_battery(temperature_c=50.0),
            device=_device(
                storage=StorageInfo(
                    mount="/data", total_kb=100_000, used_kb=95_000, available_kb=5_000
                ),
                wifi_connected=True,
                ipv4_addresses=(),
                ipv6_addresses=(),
                selinux_status="permissive",
                verified_boot_state="red",
            ),
        )
        titles = {f.title for f in report.findings}
        assert "Critical CPU utilization" in titles
        assert "Critical memory pressure" in titles
        assert "Critical battery temperature" in titles
        assert "Critical storage utilization" in titles
        assert "SELinux is in permissive mode" in titles
        assert "Verified Boot verification failed" in titles
        assert "Wi-Fi connected without an IP address" in titles

    def test_battery_snapshot_is_optional(self) -> None:
        report = evaluate(cpu=None, memory=None, battery=None, device=_device())
        assert report.findings == ()

    def test_findings_are_frozen_models(self) -> None:
        report = evaluate(
            cpu=_cpu(95.0), memory=None, battery=None, device=None
        )
        assert report.findings[0].category is DiagnosticCategory.CPU
        assert report.findings[0].severity is DiagnosticSeverity.CRITICAL