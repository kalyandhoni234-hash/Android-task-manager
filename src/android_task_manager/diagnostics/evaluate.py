"""Diagnostics evaluation: apply every rule to one snapshot bundle.

``evaluate`` is the single entry point of the diagnostics engine. It is a
pure, deterministic aggregation: the same inputs always produce the same
:class:`DiagnosticReport`. It performs no device I/O and never emits a
finding that the underlying data does not support — missing data simply
means no finding.
"""

from __future__ import annotations

from ..battery.models import BatterySnapshot
from ..cpu.models import CPUSnapshot
from ..device.models import DeviceInformation
from ..memory.models import MemorySnapshot
from .models import DiagnosticFinding, DiagnosticReport
from .rules import (
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

#: Fixed application order; grouping is a presentation concern.
_RULES = (
    battery_temperature,
    battery_health,
    battery_charging,
    storage_utilization,
    memory_pressure,
    cpu_utilization,
    wifi_without_address,
    selinux_mode,
    verified_boot,
    bootloader_lock,
    root_evidence,
    debuggable_build,
    storage_encryption,
    verity_mode,
)


def _sort_key(finding: DiagnosticFinding) -> tuple:
    """Deterministic ordering: severity (critical first), then category,
    then title."""
    return (
        -finding.severity.rank,
        finding.category.value,
        finding.title,
    )


def evaluate(
    *,
    cpu: CPUSnapshot | None,
    memory: MemorySnapshot | None,
    battery: BatterySnapshot | None,
    device: DeviceInformation | None,
) -> DiagnosticReport:
    """Evaluate one snapshot bundle and return the supported findings.

    Every snapshot is optional: ``None`` (or a snapshot whose relevant
    fields are unreadable) simply contributes no findings. The returned
    report is sorted severity-first, then by category and title.
    """
    findings: list[DiagnosticFinding] = []
    if battery is not None:
        findings.extend(battery_temperature(battery))
        findings.extend(battery_health(battery))
        findings.extend(battery_charging(battery))
    if device is not None:
        findings.extend(storage_utilization(device))
        findings.extend(wifi_without_address(device))
        findings.extend(selinux_mode(device))
        findings.extend(verified_boot(device))
        findings.extend(bootloader_lock(device))
        findings.extend(root_evidence(device))
        findings.extend(debuggable_build(device))
        findings.extend(storage_encryption(device))
        findings.extend(verity_mode(device))
    if memory is not None:
        findings.extend(memory_pressure(memory))
    if cpu is not None:
        findings.extend(cpu_utilization(cpu))
    findings.sort(key=_sort_key)
    return DiagnosticReport(findings=tuple(findings))


__all__ = ["evaluate"]