"""Deterministic device health evaluation over the live snapshots.

Every component is classified through the canonical thresholds
(:mod:`android_task_manager.thresholds`); the engine never re-declares a
threshold value. Findings are generated only from positive evidence.
"""

from __future__ import annotations

import time

from ..battery.models import BatterySnapshot
from ..cpu.models import CPUSnapshot
from ..memory.models import MemorySnapshot
from ..network.models import NetworkSnapshot
from ..process.models import ProcessCategory, ProcessSnapshot
from ..storage.models import StorageSnapshot
from ..thresholds import (
    CPU_ELEVATED_PERCENT,
    CPU_HIGH_PERCENT,
    MEMORY_USED_ELEVATED_PERCENT,
    MEMORY_USED_HIGH_PERCENT,
    classify_battery_level,
    classify_cpu,
    classify_storage,
    classify_temperature,
    classify_used_memory,
)
from .models import (
    _SCORES,
    COMPONENT_APPLICATIONS,
    COMPONENT_BATTERY,
    COMPONENT_CONNECTIVITY,
    COMPONENT_CPU,
    COMPONENT_MEMORY,
    COMPONENT_PROCESSES,
    COMPONENT_STORAGE,
    ComponentHealth,
    DeviceHealth,
    Finding,
    HealthSeverity,
    HealthStatus,
)

#: The highest severity wins for the overall status: a critical component
#: can never be masked by a healthy average.
_SEVERITY_RANK = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.WARNING: 1,
    HealthStatus.CRITICAL: 2,
}

#: A single user process holding at least this share of RAM is a memory
#: pressure signal (canonical memory-high threshold reused per process).
_PROCESS_MEMORY_WARNING_PERCENT = MEMORY_USED_HIGH_PERCENT

#: Process findings are reported for USER apps only — kernel threads and
#: system processes are excluded from "resource-intensive" claims.
_PROCESS_CATEGORY_USER = ProcessCategory.USER

#: Connectivity is considered active when at least one non-loopback
#: interface is present.
_NON_LOOPBACK_HINT = "no non-loopback network interface is present"


def _finding(
    severity: HealthSeverity,
    component: str,
    title: str,
    explanation: str,
    evidence: str,
    recommendation: str,
    now: float,
) -> Finding:
    return Finding(
        severity=severity,
        component=component,
        title=title,
        explanation=explanation,
        evidence=evidence,
        recommendation=recommendation,
        timestamp=now,
    )


def _from_level(component: str, value: float | None, level, now: float) -> ComponentHealth:
    """Component health from a canonical MetricLevel (NORMAL/ELEVATED/HIGH)."""
    if value is None:
        return ComponentHealth(component, HealthStatus.UNAVAILABLE, 0, None)
    if level.name == "HIGH":
        status = HealthStatus.CRITICAL
    elif level.name == "ELEVATED":
        status = HealthStatus.WARNING
    else:
        status = HealthStatus.HEALTHY
    return ComponentHealth(component, status, _SCORES[status], value)


def evaluate_device_health(
    *,
    cpu: CPUSnapshot | None = None,
    memory: MemorySnapshot | None = None,
    battery: BatterySnapshot | None = None,
    storage: StorageSnapshot | None = None,
    processes: ProcessSnapshot | None = None,
    network: NetworkSnapshot | None = None,
    applications_available: bool = False,
    device_serial: str | None = None,
    now: float | None = None,
) -> DeviceHealth:
    """Evaluate the unified device health from the latest snapshots.

    Every snapshot is optional: a missing snapshot makes its component
    UNAVAILABLE (never a finding). ``applications_available`` reflects
    whether an application inventory is present (the Applications
    component is healthy by inspection — an inventory read adds no
    fabricated findings).
    """
    timestamp = now if now is not None else time.time()
    findings: list[Finding] = []
    components: dict[str, ComponentHealth] = {}

    # --- CPU -----------------------------------------------------------
    cpu_value = None
    if cpu is not None:
        cpu_value = cpu.aggregate_utilization_percent
    cpu_level = classify_cpu(cpu_value) if cpu_value is not None else None
    component = _from_level(COMPONENT_CPU, cpu_value, cpu_level, timestamp)
    if cpu_level is not None and cpu_level.name == "HIGH":
        findings.append(
            _finding(
                HealthSeverity.CRITICAL,
                COMPONENT_CPU,
                "CPU utilization is critical",
                "Aggregate CPU utilization is at or above the critical threshold.",
                f"{cpu_value:.1f}% aggregate utilization (critical >= {CPU_HIGH_PERCENT:.0f}%)",
                "Inspect the process table and review the most CPU-intensive processes.",
                timestamp,
            )
        )
    elif cpu_level is not None and cpu_level.name == "ELEVATED":
        findings.append(
            _finding(
                HealthSeverity.WARNING,
                COMPONENT_CPU,
                "CPU utilization is elevated",
                "Aggregate CPU utilization is above the elevated threshold.",
                f"{cpu_value:.1f}% aggregate utilization (elevated > {CPU_ELEVATED_PERCENT:.0f}%)",
                "Review the most CPU-intensive processes under Processes.",
                timestamp,
            )
        )
    components[COMPONENT_CPU] = component

    # --- Memory ---------------------------------------------------------
    memory_value = None
    if memory is not None and memory.total_kb and memory.total_kb > 0:
        memory_value = memory.used_kb / memory.total_kb * 100.0
    memory_level = classify_used_memory(memory_value) if memory_value is not None else None
    component = _from_level(COMPONENT_MEMORY, memory_value, memory_level, timestamp)
    if memory_level is not None and memory_level.name == "HIGH":
        findings.append(
            _finding(
                HealthSeverity.CRITICAL,
                COMPONENT_MEMORY,
                "Memory pressure is critical",
                "RAM utilization is at or above the critical threshold.",
                f"{memory_value:.1f}% RAM used (critical >= {MEMORY_USED_HIGH_PERCENT:.0f}%)",
                "Review high-memory applications and consider stopping idle ones.",
                timestamp,
            )
        )
    elif memory_level is not None and memory_level.name == "ELEVATED":
        findings.append(
            _finding(
                HealthSeverity.WARNING,
                COMPONENT_MEMORY,
                "Memory pressure is elevated",
                "RAM utilization is above the elevated threshold.",
                f"{memory_value:.1f}% RAM used (elevated > {MEMORY_USED_ELEVATED_PERCENT:.0f}%)",
                "Review high-memory applications under Processes.",
                timestamp,
            )
        )
    components[COMPONENT_MEMORY] = component

    # --- Battery --------------------------------------------------------
    battery_level_value = battery.level_percent if battery is not None else None
    battery_level = (
        classify_battery_level(battery_level_value) if battery_level_value is not None else None
    )
    battery_status = HealthStatus.UNAVAILABLE
    if battery is not None:
        battery_status = (
            HealthStatus.CRITICAL
            if battery_level is not None and battery_level.name == "HIGH"
            else HealthStatus.WARNING
            if battery_level is not None and battery_level.name == "ELEVATED"
            else HealthStatus.HEALTHY
        )
        if battery.temperature_c is not None:
            temperature_level = classify_temperature(battery.temperature_c)
            if temperature_level is not None and temperature_level.name != "NORMAL":
                battery_status = (
                    HealthStatus.CRITICAL
                    if temperature_level.name == "HIGH"
                    else HealthStatus.WARNING
                )
    component = ComponentHealth(
        COMPONENT_BATTERY, battery_status, _SCORES[battery_status], battery_level_value
    )
    if battery_level is not None and battery_level.name == "HIGH":
        findings.append(
            _finding(
                HealthSeverity.CRITICAL,
                COMPONENT_BATTERY,
                "Battery level is critical",
                "The battery level is at or below the critical threshold.",
                f"{battery_level_value:.0f}% level (critical <= 20%)",
                "Connect the device to power.",
                timestamp,
            )
        )
    elif battery_level is not None and battery_level.name == "ELEVATED":
        findings.append(
            _finding(
                HealthSeverity.WARNING,
                COMPONENT_BATTERY,
                "Battery level is low",
                "The battery level is at or below the elevated threshold.",
                f"{battery_level_value:.0f}% level (elevated <= 35%)",
                "Consider connecting the device to power.",
                timestamp,
            )
        )
    if battery is not None and battery.temperature_c is not None:
        temperature_level = classify_temperature(battery.temperature_c)
        if temperature_level is not None and temperature_level.name == "HIGH":
            findings.append(
                _finding(
                    HealthSeverity.CRITICAL,
                    COMPONENT_BATTERY,
                    "Battery temperature is high",
                    "The battery temperature is at or above the critical threshold.",
                    f"{battery.temperature_c:.1f} C (critical >= 45 C)",
                    "Stop heavy load and let the device cool down.",
                    timestamp,
                )
            )
        elif temperature_level is not None and temperature_level.name == "ELEVATED":
            findings.append(
                _finding(
                    HealthSeverity.WARNING,
                    COMPONENT_BATTERY,
                    "Battery temperature is elevated",
                    "The battery temperature is above the elevated threshold.",
                    f"{battery.temperature_c:.1f} C (elevated > 40 C)",
                    "Monitor the temperature; reduce heavy load if it keeps rising.",
                    timestamp,
                )
            )
    components[COMPONENT_BATTERY] = component

    # --- Storage ---------------------------------------------------------
    storage_value = storage.used_percent if storage is not None else None
    storage_level = classify_storage(storage_value) if storage_value is not None else None
    component = _from_level(COMPONENT_STORAGE, storage_value, storage_level, timestamp)
    if storage_level is not None and storage_level.name == "HIGH":
        findings.append(
            _finding(
                HealthSeverity.CRITICAL,
                COMPONENT_STORAGE,
                "Internal storage is critical",
                "The internal storage volume is at or above the critical threshold.",
                f"{storage_value:.1f}% used (critical >= 90%)",
                "Free space on the internal storage volume.",
                timestamp,
            )
        )
    elif storage_level is not None and storage_level.name == "ELEVATED":
        findings.append(
            _finding(
                HealthSeverity.WARNING,
                COMPONENT_STORAGE,
                "Internal storage is nearly full",
                "The internal storage volume is above the elevated threshold.",
                f"{storage_value:.1f}% used (elevated > 80%)",
                "Review large applications and stored files.",
                timestamp,
            )
        )
    components[COMPONENT_STORAGE] = component

    # --- Processes -------------------------------------------------------
    processes_status = HealthStatus.UNAVAILABLE
    process_evidence: list[str] = []
    if processes is not None:
        heavy_cpu = None
        heavy_memory = None
        for process in processes.processes:
            if process.category != _PROCESS_CATEGORY_USER:
                continue
            if process.cpu_percent is not None and process.cpu_percent >= CPU_HIGH_PERCENT:
                if heavy_cpu is None or process.cpu_percent > heavy_cpu[0]:
                    heavy_cpu = (process.cpu_percent, process.name, process.pid)
            if (
                process.memory_percent is not None
                and process.memory_percent >= _PROCESS_MEMORY_WARNING_PERCENT
            ):
                if heavy_memory is None or process.memory_percent > heavy_memory[0]:
                    heavy_memory = (process.memory_percent, process.name, process.pid)
        if heavy_cpu is not None:
            processes_status = HealthStatus.CRITICAL
            percent, name, pid = heavy_cpu
            process_evidence.append(f"{name} (pid {pid}) at {percent:.1f}% CPU")
            findings.append(
                _finding(
                    HealthSeverity.CRITICAL,
                    COMPONENT_PROCESSES,
                    "A user process is using extreme CPU",
                    "A user application process is at or above the critical CPU threshold.",
                    f"{name} (pid {pid}) {percent:.1f}% CPU (critical >= {CPU_HIGH_PERCENT:.0f}%)",
                    "Review the process under Processes; Force Stop is available in its inspector.",
                    timestamp,
                )
            )
        elif heavy_memory is not None:
            processes_status = HealthStatus.WARNING
            percent, name, pid = heavy_memory
            process_evidence.append(f"{name} (pid {pid}) at {percent:.1f}% RAM")
            findings.append(
                _finding(
                    HealthSeverity.WARNING,
                    COMPONENT_PROCESSES,
                    "A user process holds a large share of RAM",
                    "A single user application process holds a large share of RAM.",
                    f"{name} (pid {pid}) {percent:.1f}% RAM (>= {_PROCESS_MEMORY_WARNING_PERCENT:.0f}%)",
                    "Review the process under Processes; consider stopping it if idle.",
                    timestamp,
                )
            )
        elif heavy_cpu is None and heavy_memory is None:
            processes_status = HealthStatus.HEALTHY
    component = ComponentHealth(
        COMPONENT_PROCESSES,
        processes_status,
        _SCORES[processes_status],
        None,
        findings=tuple(
            finding for finding in findings if finding.component == COMPONENT_PROCESSES
        ),
    )
    components[COMPONENT_PROCESSES] = component

    # --- Applications ----------------------------------------------------
    applications_status = (
        HealthStatus.HEALTHY if applications_available else HealthStatus.UNAVAILABLE
    )
    components[COMPONENT_APPLICATIONS] = ComponentHealth(
        COMPONENT_APPLICATIONS, applications_status, _SCORES[applications_status], None
    )

    # --- Connectivity ----------------------------------------------------
    connectivity_status = HealthStatus.UNAVAILABLE
    if network is not None:
        non_loopback = [
            interface.name
            for interface in network.interfaces
            if interface.name != "lo"
        ]
        if non_loopback:
            connectivity_status = HealthStatus.HEALTHY
        else:
            connectivity_status = HealthStatus.WARNING
            findings.append(
                _finding(
                    HealthSeverity.WARNING,
                    COMPONENT_CONNECTIVITY,
                    "No active network interface seen",
                    "The device reports interfaces, but none is non-loopback.",
                    _NON_LOOPBACK_HINT,
                    "Check the device's Wi-Fi / mobile data state under Network.",
                    timestamp,
                )
            )
    components[COMPONENT_CONNECTIVITY] = ComponentHealth(
        COMPONENT_CONNECTIVITY, connectivity_status, _SCORES[connectivity_status], None
    )

    # --- Overall -----------------------------------------------------------
    available = [
        component
        for component in components.values()
        if component.status is not HealthStatus.UNAVAILABLE
    ]
    if not available:
        overall_score = None
        overall_status = HealthStatus.UNAVAILABLE
    else:
        overall_score = round(
            sum(component.score for component in available) / len(available), 1
        )
        worst = max(
            (component.status for component in available),
            key=lambda status: _SEVERITY_RANK[status],
        )
        overall_status = worst

    return DeviceHealth(
        overall_score=overall_score,
        status=overall_status,
        components=components,
        findings=findings,
        evaluated_at=timestamp,
        device_serial=device_serial,
    )


__all__ = ["evaluate_device_health"]
