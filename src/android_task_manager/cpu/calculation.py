"""CPU utilization computed from deltas between two /proc/stat samples."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CPUCounters


@dataclass(frozen=True)
class CPUDelta:
    """Signed tick deltas between two CPU counter samples."""

    #: ``None`` for the aggregate "cpu" delta.
    core_id: int | None
    busy: int
    total: int


def calculate_delta(previous: CPUCounters, current: CPUCounters) -> CPUDelta:
    """Compute busy/total tick deltas between two observations of one CPU."""
    if previous.core_id != current.core_id:
        raise ValueError(
            f"Cannot compute CPU delta for mismatched cores: "
            f"previous={previous.core_id!r}, current={current.core_id!r}"
        )

    # busy = user + nice + system + irq + softirq
    busy = (
        (current.user - previous.user)
        + (current.nice - previous.nice)
        + (current.system - previous.system)
        + (current.irq - previous.irq)
        + (current.softirq - previous.softirq)
    )
    # total = busy + idle + iowait
    # guest time is already included in user/nice, so it is not added again;
    # steal/guest_nice are excluded for this kernel's 7-field accounting.
    total = busy + (current.idle - previous.idle) + (current.iowait - previous.iowait)
    return CPUDelta(core_id=current.core_id, busy=busy, total=total)


def utilization_percent(delta: CPUDelta) -> float:
    """Return busy/total as a percentage clamped to [0, 100].

    A zero total delta (e.g. a tickless idle CPU, or two identical snapshots)
    has no measurable activity and yields 0.0%. Small counter anomalies that
    push the value slightly out of range are clamped.
    """
    if delta.total <= 0:
        return 0.0
    percent = delta.busy / delta.total * 100.0
    return min(100.0, max(0.0, percent))