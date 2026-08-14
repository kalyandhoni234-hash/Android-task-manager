"""Normalized CPU data models.

These dataclasses are the contract between the CPU collector, the delta
calculation, and the terminal renderer. Raw adb/subprocess output never reaches
the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CPUCounters:
    """Raw /proc/stat tick counters for one CPU (or the aggregate ``cpu``)."""

    #: ``None`` for the aggregate "cpu" line, otherwise the numeric cpuN id.
    core_id: int | None
    user: int
    nice: int
    system: int
    idle: int
    iowait: int
    irq: int
    softirq: int


@dataclass(frozen=True)
class ProcStat:
    """Result of parsing an entire ``/proc/stat`` read."""

    #: Counters for the aggregate ``cpu`` line. Never None on a valid parse.
    aggregate: CPUCounters
    #: One entry per discovered core (cpu0..cpuN), sorted by core id.
    cores: list[CPUCounters] = field(default_factory=list)


@dataclass(frozen=True)
class CPUCore:
    """Normalized per-core CPU state for presentation."""

    core_id: int
    #: ``None`` means "no previous sample yet" (first sample) — not a fake 0%.
    utilization_percent: float | None
    #: Frequency in kHz; ``None`` when unreadable/not available.
    frequency_khz: int | None
    frequency_available: bool


@dataclass(frozen=True)
class CPUSnapshot:
    """A fully-normalized view of the device CPU at one moment."""

    #: Monotonic timestamp of the sample (best effort).
    timestamp: float
    #: Aggregate CPU utilization; ``None`` on the first sample.
    aggregate_utilization_percent: float | None
    #: Normalized per-core utilization + frequency.
    cores: list[CPUCore]
    #: Raw counters retained for calculation/debugging/derive later metrics.
    aggregate_counters: CPUCounters | None = None
    core_counters: list[CPUCounters] | None = None