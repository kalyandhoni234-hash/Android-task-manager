"""Tests for the device health engine (Phase B).

Covers healthy / warning / critical / unavailable states, deterministic
scoring, finding generation, threshold reuse (canonical values, never
duplicated) and the no-fabrication invariant on missing data.
"""

from __future__ import annotations

import pytest

from android_task_manager.battery.models import BatterySnapshot
from android_task_manager.cpu.models import CPUSnapshot
from android_task_manager.health import (
    COMPONENT_APPLICATIONS,
    COMPONENT_BATTERY,
    COMPONENT_CONNECTIVITY,
    COMPONENT_CPU,
    COMPONENT_MEMORY,
    COMPONENT_PROCESSES,
    COMPONENT_STORAGE,
    HealthStatus,
    evaluate_device_health,
)
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.network.models import NetworkInterfaceSnapshot, NetworkSnapshot
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot
from android_task_manager.storage.models import StorageSnapshot
from android_task_manager.thresholds import (
    BATTERY_LEVEL_ELEVATED_PERCENT,
    BATTERY_LEVEL_HIGH_PERCENT,
    CPU_ELEVATED_PERCENT,
    CPU_HIGH_PERCENT,
    MEMORY_USED_ELEVATED_PERCENT,
    MEMORY_USED_HIGH_PERCENT,
    STORAGE_USED_ELEVATED_PERCENT,
    STORAGE_USED_HIGH_PERCENT,
    TEMPERATURE_ELEVATED_C,
    TEMPERATURE_HIGH_C,
)


def _cpu(percent: float | None) -> CPUSnapshot:
    return CPUSnapshot(
        timestamp=1.0,
        aggregate_utilization_percent=percent,
        cores=(),
    )


def _memory(used_percent: float | None) -> MemorySnapshot:
    if used_percent is None:
        return MemorySnapshot(timestamp=1.0)
    return MemorySnapshot(
        timestamp=1.0,
        total_kb=100_000,
        free_kb=0,
        available_kb=100_000 * (1 - used_percent / 100.0),
        buffers_kb=0,
        cached_kb=0,
        swap_cached_kb=0,
    )


def _battery(level: float | None, temperature_c: float | None = None) -> BatterySnapshot:
    return BatterySnapshot(
        timestamp=1.0,
        level_percent=level,
        scale=None,
        voltage_mv=None,
        temperature_c=temperature_c,
        status=None,
        status_raw=None,
        health=None,
        health_raw=None,
        present=None,
        ac_powered=None,
        usb_powered=None,
        wireless_powered=None,
        technology="Li-poly",
        charge_counter=None,
    )


def _storage(used_percent: float | None) -> StorageSnapshot:
    if used_percent is None:
        return StorageSnapshot(timestamp=1.0, mount="/data")
    return StorageSnapshot(
        timestamp=1.0,
        mount="/data",
        total_kb=1_000_000,
        used_kb=1_000_000 * used_percent / 100.0,
        available_kb=1_000_000 * (1 - used_percent / 100.0),
    )


def _processes(*infos: ProcessInfo) -> ProcessSnapshot:
    return ProcessSnapshot(timestamp=1.0, processes=list(infos))


def _user_process(cpu_percent: float | None, memory_percent: float | None, name="com.example.app") -> ProcessInfo:
    return ProcessInfo(
        pid=8150,
        name=name,
        uid=10001,
        state="R",
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        category=ProcessCategory.USER,
    )


def _network(*names: str) -> NetworkSnapshot:
    interfaces = tuple(
        NetworkInterfaceSnapshot(
            name=name,
            rx_bytes=0,
            tx_bytes=0,
            rx_packets=0,
            tx_packets=0,
            rx_errors=0,
            tx_errors=0,
            rx_drops=0,
            tx_drops=0,
        )
        for name in names
    )
    return NetworkSnapshot(
        timestamp=1.0,
        interfaces=interfaces,
        aggregate_rx_bytes=0,
        aggregate_tx_bytes=0,
        aggregate_rx_packets=0,
        aggregate_tx_packets=0,
        aggregate_rx_errors=0,
        aggregate_tx_errors=0,
        aggregate_rx_drops=0,
        aggregate_tx_drops=0,
        interface_throughput={},
        aggregate_throughput=None,
    )


def _all_healthy() -> dict:
    return dict(
        cpu=_cpu(30.0),
        memory=_memory(40.0),
        battery=_battery(80.0),
        storage=_storage(50.0),
        processes=_processes(_user_process(10.0, 5.0)),
        network=_network("wlan0", "lo"),
        applications_available=True,
        now=100.0,
    )


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------


def test_fully_healthy_device() -> None:
    health = evaluate_device_health(**_all_healthy())
    assert health.status is HealthStatus.HEALTHY
    assert health.overall_score == 100.0
    assert health.findings == []
    for component in (
        COMPONENT_CPU,
        COMPONENT_MEMORY,
        COMPONENT_BATTERY,
        COMPONENT_STORAGE,
        COMPONENT_PROCESSES,
        COMPONENT_APPLICATIONS,
        COMPONENT_CONNECTIVITY,
    ):
        assert health.component(component).status is HealthStatus.HEALTHY


def test_unavailable_device_produces_unavailable_health() -> None:
    health = evaluate_device_health(now=100.0)
    assert health.status is HealthStatus.UNAVAILABLE
    assert health.overall_score is None
    assert health.findings == []  # missing data is never a finding
    for component in (
        COMPONENT_CPU,
        COMPONENT_MEMORY,
        COMPONENT_BATTERY,
        COMPONENT_STORAGE,
        COMPONENT_PROCESSES,
        COMPONENT_APPLICATIONS,
        COMPONENT_CONNECTIVITY,
    ):
        assert health.component(component).status is HealthStatus.UNAVAILABLE


def test_critical_component_dominates_overall_status() -> None:
    # Critical CPU + everything else healthy: status must be CRITICAL even
    # though the average is high — the score must never hide a problem.
    data = _all_healthy()
    data["cpu"] = _cpu(CPU_HIGH_PERCENT)
    health = evaluate_device_health(**data)
    assert health.status is HealthStatus.CRITICAL
    assert health.component(COMPONENT_CPU).status is HealthStatus.CRITICAL
    assert health.overall_score < 100.0


def test_warning_component_dominates_overall_status() -> None:
    data = _all_healthy()
    data["memory"] = _memory(MEMORY_USED_ELEVATED_PERCENT + 1.0)
    health = evaluate_device_health(**data)
    assert health.status is HealthStatus.WARNING
    assert health.component(COMPONENT_MEMORY).status is HealthStatus.WARNING


def test_single_component_unavailable_is_not_a_finding() -> None:
    data = _all_healthy()
    data["storage"] = None
    health = evaluate_device_health(**data)
    assert health.component(COMPONENT_STORAGE).status is HealthStatus.UNAVAILABLE
    assert health.status is HealthStatus.HEALTHY  # other components still fine
    assert not any(f.component == COMPONENT_STORAGE for f in health.findings)


# ---------------------------------------------------------------------------
# Finding generation
# ---------------------------------------------------------------------------


def test_cpu_critical_finding() -> None:
    data = _all_healthy()
    data["cpu"] = _cpu(CPU_HIGH_PERCENT)
    health = evaluate_device_health(**data)
    findings = [f for f in health.findings if f.component == COMPONENT_CPU]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity.value == "critical"
    assert finding.title == "CPU utilization is critical"
    assert str(CPU_HIGH_PERCENT) in finding.evidence
    assert finding.recommendation
    assert finding.timestamp == 100.0


def test_cpu_warning_finding() -> None:
    data = _all_healthy()
    data["cpu"] = _cpu(CPU_ELEVATED_PERCENT + 1.0)
    health = evaluate_device_health(**data)
    findings = [f for f in health.findings if f.component == COMPONENT_CPU]
    assert len(findings) == 1
    assert findings[0].severity.value == "warning"


def test_memory_critical_and_warning_findings() -> None:
    data = _all_healthy()
    data["memory"] = _memory(MEMORY_USED_HIGH_PERCENT)
    health = evaluate_device_health(**data)
    assert any(
        f.severity.value == "critical" and f.component == COMPONENT_MEMORY
        for f in health.findings
    )
    data["memory"] = _memory(MEMORY_USED_ELEVATED_PERCENT + 1.0)
    health = evaluate_device_health(**data)
    assert any(
        f.severity.value == "warning" and f.component == COMPONENT_MEMORY
        for f in health.findings
    )


def test_battery_low_critical_and_warning_findings() -> None:
    data = _all_healthy()
    data["battery"] = _battery(BATTERY_LEVEL_HIGH_PERCENT)
    health = evaluate_device_health(**data)
    assert any(
        f.severity.value == "critical" and f.component == COMPONENT_BATTERY
        for f in health.findings
    )
    data["battery"] = _battery(BATTERY_LEVEL_ELEVATED_PERCENT - 1.0)
    health = evaluate_device_health(**data)
    assert any(
        f.severity.value == "warning" and f.component == COMPONENT_BATTERY
        for f in health.findings
    )


def test_battery_temperature_findings() -> None:
    data = _all_healthy()
    data["battery"] = _battery(80.0, temperature_c=TEMPERATURE_HIGH_C)
    health = evaluate_device_health(**data)
    assert any(
        f.severity.value == "critical" and "temperature" in f.title
        for f in health.findings
    )
    data["battery"] = _battery(80.0, temperature_c=TEMPERATURE_ELEVATED_C + 0.1)
    health = evaluate_device_health(**data)
    assert any(
        f.severity.value == "warning" and "temperature" in f.title
        for f in health.findings
    )
    data["battery"] = _battery(80.0, temperature_c=None)
    health = evaluate_device_health(**data)
    assert not any("temperature" in f.title for f in health.findings)


def test_storage_findings() -> None:
    data = _all_healthy()
    data["storage"] = _storage(STORAGE_USED_HIGH_PERCENT)
    health = evaluate_device_health(**data)
    assert any(
        f.severity.value == "critical" and f.component == COMPONENT_STORAGE
        for f in health.findings
    )
    data["storage"] = _storage(STORAGE_USED_ELEVATED_PERCENT + 1.0)
    health = evaluate_device_health(**data)
    assert any(
        f.severity.value == "warning" and f.component == COMPONENT_STORAGE
        for f in health.findings
    )


def test_process_cpu_finding_ignores_system_and_kernel() -> None:
    kernel = ProcessInfo(
        pid=17, name="kworker/0:1", uid=0, state="R",
        cpu_percent=CPU_HIGH_PERCENT, memory_percent=1.0, category=ProcessCategory.KERNEL_THREAD,
    )
    system = ProcessInfo(
        pid=1054, name="system_server", uid=1000, state="R",
        cpu_percent=CPU_HIGH_PERCENT, memory_percent=1.0, category=ProcessCategory.SYSTEM,
    )
    health = evaluate_device_health(
        processes=_processes(kernel, system),
        now=100.0,
    )
    assert health.component(COMPONENT_PROCESSES).status is HealthStatus.HEALTHY
    assert not any(f.component == COMPONENT_PROCESSES for f in health.findings)


def test_process_cpu_critical_finding() -> None:
    health = evaluate_device_health(
        processes=_processes(_user_process(CPU_HIGH_PERCENT, 5.0)),
        now=100.0,
    )
    assert health.component(COMPONENT_PROCESSES).status is HealthStatus.CRITICAL
    findings = [f for f in health.findings if f.component == COMPONENT_PROCESSES]
    assert len(findings) == 1
    assert findings[0].severity.value == "critical"
    assert "com.example.app" in findings[0].evidence
    assert "pid 8150" in findings[0].evidence


def test_process_memory_warning_finding() -> None:
    health = evaluate_device_health(
        processes=_processes(_user_process(5.0, MEMORY_USED_HIGH_PERCENT)),
        now=100.0,
    )
    assert health.component(COMPONENT_PROCESSES).status is HealthStatus.WARNING
    findings = [f for f in health.findings if f.component == COMPONENT_PROCESSES]
    assert len(findings) == 1
    assert findings[0].severity.value == "warning"


def test_connectivity_warning_when_only_loopback() -> None:
    data = _all_healthy()
    data["network"] = _network("lo")
    health = evaluate_device_health(**data)
    assert health.component(COMPONENT_CONNECTIVITY).status is HealthStatus.WARNING
    assert any(
        f.component == COMPONENT_CONNECTIVITY and f.severity.value == "warning"
        for f in health.findings
    )


def test_connectivity_healthy_with_non_loopback() -> None:
    data = _all_healthy()
    data["network"] = _network("wlan0", "lo")
    health = evaluate_device_health(**data)
    assert health.component(COMPONENT_CONNECTIVITY).status is HealthStatus.HEALTHY
    assert not any(f.component == COMPONENT_CONNECTIVITY for f in health.findings)


def test_connectivity_unavailable_without_network_snapshot() -> None:
    data = _all_healthy()
    data["network"] = None
    health = evaluate_device_health(**data)
    assert health.component(COMPONENT_CONNECTIVITY).status is HealthStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# Determinism & scoring
# ---------------------------------------------------------------------------


def test_scoring_is_deterministic() -> None:
    first = evaluate_device_health(**_all_healthy())
    second = evaluate_device_health(**_all_healthy())
    assert first.overall_score == second.overall_score
    assert first.status is second.status


def test_healthy_score_is_100() -> None:
    health = evaluate_device_health(**_all_healthy())
    assert health.overall_score == 100.0


def test_warning_score_uses_canonical_70() -> None:
    data = _all_healthy()
    data["storage"] = _storage(STORAGE_USED_ELEVATED_PERCENT + 1.0)
    health = evaluate_device_health(**data)
    assert health.component(COMPONENT_STORAGE).score == 70
    # 6 healthy (100) + 1 warning (70) → mean of available components
    # (engine rounds the overall score to one decimal).
    assert health.overall_score == pytest.approx((6 * 100 + 70) / 7, abs=0.05)


def test_critical_score_uses_canonical_40() -> None:
    data = _all_healthy()
    data["cpu"] = _cpu(CPU_HIGH_PERCENT)
    health = evaluate_device_health(**data)
    assert health.component(COMPONENT_CPU).score == 40


def test_findings_ordered_by_generation() -> None:
    data = _all_healthy()
    data["cpu"] = _cpu(CPU_HIGH_PERCENT)
    data["storage"] = _storage(STORAGE_USED_ELEVATED_PERCENT + 1.0)
    health = evaluate_device_health(**data)
    components = [f.component for f in health.findings]
    assert components.index(COMPONENT_CPU) < components.index(COMPONENT_STORAGE)


def test_device_serial_and_timestamp_recorded() -> None:
    health = evaluate_device_health(**_all_healthy(), device_serial="FAKE123")
    assert health.device_serial == "FAKE123"
    assert health.evaluated_at == 100.0
