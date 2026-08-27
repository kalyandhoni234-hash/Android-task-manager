"""Pure translation from existing monitor snapshots to performance metrics.

This module is the single place that knows how to read a
``CPUSnapshot`` / ``MemorySnapshot`` / ``BatterySnapshot`` / ``StorageSnapshot``
/ ``ProcessSnapshot`` / ``NetworkSnapshot`` / ``BackgroundAppsSnapshot`` and
turn it into the plain ``float`` metrics the performance domain consumes.

It performs **no** collection, **no** ADB, **no** Qt. The derivation rules are
identical to the rest of the application (e.g. memory used = total − available,
CPU = ``aggregate_utilization_percent``) so the performance metrics are
consistent with the live dashboard and health engine.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..background.models import BackgroundAppsSnapshot
from ..battery.models import BatterySnapshot
from ..cpu.models import CPUSnapshot
from ..memory.models import MemorySnapshot
from ..network.models import NetworkSnapshot
from ..process.models import ProcessSnapshot
from ..storage.models import StorageSnapshot

__all__ = [
    "app_loads_from_background",
    "battery_level_percent",
    "cpu_used_percent",
    "memory_used_percent",
    "network_throughput",
    "process_count",
    "storage_used_percent",
]


def cpu_used_percent(cpu: CPUSnapshot | None) -> float | None:
    if cpu is None:
        return None
    return cpu.aggregate_utilization_percent


def memory_used_percent(memory: MemorySnapshot | None) -> float | None:
    """Used share of total RAM (used = total − available); None when unknown."""
    if memory is None or memory.total_kb <= 0:
        return None
    used = max(0, memory.total_kb - memory.available_kb)
    return used / memory.total_kb * 100.0


def battery_level_percent(battery: BatterySnapshot | None) -> float | None:
    if battery is None:
        return None
    return battery.level_percent


def storage_used_percent(storage: StorageSnapshot | None) -> float | None:
    if storage is None:
        return None
    return storage.used_percent


def process_count(processes: ProcessSnapshot | None) -> int | None:
    if processes is None:
        return None
    return len(processes.processes)


def network_throughput(
    network: NetworkSnapshot | None,
) -> tuple[float | None, float | None]:
    """(rx_bytes_per_s, tx_bytes_per_s) from the aggregate throughput."""
    if network is None:
        return (None, None)
    agg = network.aggregate_throughput
    return (agg.rx_bytes_per_sec, agg.tx_bytes_per_sec)


def app_loads_from_background(
    background: BackgroundAppsSnapshot | None,
) -> Sequence[tuple[str, str | None, float | None, float | None]]:
    """Already-resolved application loads from the v0.8.1 background pipeline.

    The identity (process → UID → verified package → label) has already been
    resolved by ``build_background_apps``; this function only re-packages the
    resolved entries into the ``(package, label, cpu, memory)`` shape the
    analyzer consumes. Nothing is re-resolved here.
    """
    if background is None:
        return ()
    loads: list[tuple[str, str | None, float | None, float | None]] = []
    for entry in background.entries:
        loads.append(
            (entry.package_name, entry.label, entry.cpu_percent, entry.memory_percent)
        )
    return loads
