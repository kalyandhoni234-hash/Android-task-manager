"""Device event timeline — models.

The timeline is the unified chronological event log of the device
intelligence engine (device sessions, health transitions, rule firing,
automation). Events reference evidence by identity vocabulary
(``evidence_refs``) instead of embedding snapshots — mirroring the
investigation timeline template (``investigation/models.py``), including
the deterministic ``T-###`` event-id scheme.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: Canonical timeline event types. New keys are added here, never fabricated.
EVENT_SESSION_STARTED = "SESSION_STARTED"
EVENT_DEVICE_CONNECTED = "DEVICE_CONNECTED"
EVENT_DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
EVENT_HEALTH_CHANGED = "HEALTH_CHANGED"
EVENT_METRIC_ALERT = "METRIC_ALERT"
EVENT_RULE_FIRED = "RULE_FIRED"
EVENT_RECOMMENDATION = "RECOMMENDATION"
EVENT_ACTION_EXECUTED = "ACTION_EXECUTED"

#: Canonical severities used on the timeline (kept in lockstep with the
#: health vocabulary).
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


@dataclass(frozen=True)
class TimelineEvent:
    """One dated event on the device timeline.

    * ``event_id`` — deterministic, session-scoped ``T-###`` sequence.
    * ``timestamp`` — wall clock when available; ``monotonic`` — the
      collector's monotonic clock. Either can be ``None``; a missing clock
      is never fabricated (ordering comes from the sequence).
    * ``device_serial`` — the serial of the device this event belongs to.
    * ``evidence_refs`` — identity vocabulary references (process names,
      package names, findings), never embedded data.
    """

    event_id: str  # "T-001" — assigned after deterministic ordering
    event_type: str
    title: str
    description: str
    timestamp: datetime | None = None
    monotonic: float | None = None
    device_serial: str | None = None
    severity: str | None = None
    entity: str | None = None
    evidence_refs: tuple[str, ...] = ()


__all__ = [
    "EVENT_ACTION_EXECUTED",
    "EVENT_DEVICE_CONNECTED",
    "EVENT_DEVICE_DISCONNECTED",
    "EVENT_HEALTH_CHANGED",
    "EVENT_METRIC_ALERT",
    "EVENT_RECOMMENDATION",
    "EVENT_RULE_FIRED",
    "EVENT_SESSION_STARTED",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "TimelineEvent",
]
