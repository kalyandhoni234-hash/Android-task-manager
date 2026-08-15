"""Normalized process data models.

Processes are identified authoritatively from ``ps`` output (PID/UID/NAME).
Dynamic CPU/memory percentages come from ``top`` and are merged on PID. The
renderer only ever sees a ``ProcessSnapshot`` of ``ProcessInfo`` rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProcessCategory(Enum):
    """A coarse, documented classification of a process.

    This is intentionally a heuristic (kernel threads vs. system vs. user
    apps), not a perfect Android process taxonomy. See ``classify_process``.
    """

    KERNEL_THREAD = "kernel"
    SYSTEM = "system"
    USER = "user"


@dataclass(frozen=True)
class ProcessIdentity:
    """A process as reported by ``ps -A -o PID,PPID,UID,NAME``.

    ``ppid`` is ``None`` only when the collector could not provide a
    parent (e.g. output without a PPID column) — never inferred.
    """

    pid: int
    uid: int
    name: str
    ppid: int | None = None


@dataclass(frozen=True)
class ProcessCPUMetrics:
    """A process row parsed from ``top`` output (dynamic metrics)."""

    pid: int
    #: Name from top — may be truncated; used only as a fallback because ps is
    #: authoritative for names.
    name: str | None = None
    state: str | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None


@dataclass(frozen=True)
class ProcessInfo:
    """A single normalized process row ready for presentation."""

    pid: int
    name: str
    uid: int | None
    state: str | None
    cpu_percent: float | None
    memory_percent: float | None
    category: ProcessCategory
    ppid: int | None = None


@dataclass(frozen=True)
class ProcessSnapshot:
    """A normalized view of the device's top-reported processes at one moment.

    Only processes `top` supplied dynamic metrics for are included; ps identity
    (UID/name/category) is merged in by PID where available.
    """

    #: Monotonic timestamp of the sample.
    timestamp: float
    processes: list[ProcessInfo] = field(default_factory=list)