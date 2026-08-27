"""Performance event model and Timeline adapter.

The timeline (:mod:`android_task_manager.timeline`) is the project's unified
chronological event log. Its :class:`TimelineEvent` has a fixed, shared shape:
a deterministic ``T-###`` ``event_id`` assigned after ordering, severity as a
lowercase string, and ``evidence_refs`` as identity vocabulary (never embedded
data).

The performance layer therefore does **not** try to make ``TimelineEvent``
consume its events directly. Instead it defines a normalized
:class:`PerformanceEvent` (with its own typed ``PerformanceEventType`` and a
frozen ``evidence_ids`` tuple) and a single :func:`to_timeline_event` adapter
that maps a performance event onto a ``TimelineEvent``. The adapter is the only
place that knows both vocabularies, so neither module must import the other's
domain type to record an event.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..timeline.models import (
    EVENT_METRIC_ALERT,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    TimelineEvent,
)

#: Performance event types (internal vocabulary).
_EVENT_TYPE_TO_TIMELINE = {
    "cpu_pressure": EVENT_METRIC_ALERT,
    "memory_pressure": EVENT_METRIC_ALERT,
    "battery_drain": EVENT_METRIC_ALERT,
    "storage_pressure": EVENT_METRIC_ALERT,
    "process_pressure": EVENT_METRIC_ALERT,
    "application_pressure": EVENT_METRIC_ALERT,
    "baseline_deviation": EVENT_METRIC_ALERT,
    "anomaly": EVENT_METRIC_ALERT,
    "episode_recovery": EVENT_METRIC_ALERT,
}

_SEVERITY_TO_TIMELINE = {
    "info": SEVERITY_INFO,
    "warning": SEVERITY_WARNING,
    "critical": SEVERITY_CRITICAL,
}


class PerformanceEventType(str, Enum):
    """Normalized performance event kinds."""

    CPU_PRESSURE = "cpu_pressure"
    MEMORY_PRESSURE = "memory_pressure"
    BATTERY_DRAIN = "battery_drain"
    STORAGE_PRESSURE = "storage_pressure"
    PROCESS_PRESSURE = "process_pressure"
    APPLICATION_PRESSURE = "application_pressure"
    BASELINE_DEVIATION = "baseline_deviation"
    ANOMALY = "anomaly"
    #: One grouped performance episode reached RECOVERED (one event per
    #: episode, never per tick). Maps to the shared metric-alert timeline type.
    EPISODE_RECOVERY = "episode_recovery"


@dataclass(frozen=True)
class PerformanceEvent:
    """One normalized performance event.

    ``evidence_ids`` references :class:`PerformanceEvidence` by id — never the
    embedded numbers — so the timeline stays a lightweight index, matching the
    existing timeline contract.
    """

    timestamp: float
    event_type: PerformanceEventType
    severity: str
    title: str
    description: str
    entity: str | None = None
    evidence_ids: tuple[str, ...] = ()
    device_serial: str | None = None


def to_timeline_event(
    event: PerformanceEvent,
    *,
    event_id: str,
    device_serial: str | None = None,
) -> TimelineEvent:
    """Adapt a :class:`PerformanceEvent` to a shared ``TimelineEvent``.

    ``event_id`` is assigned by the caller (deterministic ``T-###`` ordering).
    The timeline severity vocabulary is reused verbatim; any unknown severity
    falls back to ``info`` rather than fabricating a level.
    """
    timeline_type = _EVENT_TYPE_TO_TIMELINE.get(
        event.event_type.value, EVENT_METRIC_ALERT
    )
    severity = _SEVERITY_TO_TIMELINE.get(event.severity, SEVERITY_INFO)
    return TimelineEvent(
        event_id=event_id,
        event_type=timeline_type,
        title=event.title,
        description=event.description,
        timestamp=None,
        monotonic=event.timestamp,
        device_serial=device_serial or event.device_serial,
        severity=severity,
        entity=event.entity,
        evidence_refs=tuple(event.evidence_ids),
    )


__all__ = [
    "PerformanceEvent",
    "PerformanceEventType",
    "to_timeline_event",
]
