"""Device event timeline — bounded, per-session, deduplicating event log.

Pure and GUI-independent: the timeline records device-session events,
health transitions, rule firing and automation actions with deterministic
ids, wall-clock and monotonic timestamps, and suppresses repeated states
(meaningful transitions only).
"""

from .engine import DEFAULT_MAX_EVENTS, EventTimeline
from .models import (
    EVENT_ACTION_EXECUTED,
    EVENT_DEVICE_CONNECTED,
    EVENT_DEVICE_DISCONNECTED,
    EVENT_HEALTH_CHANGED,
    EVENT_METRIC_ALERT,
    EVENT_RECOMMENDATION,
    EVENT_RULE_FIRED,
    EVENT_SESSION_STARTED,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    TimelineEvent,
)

__all__ = [
    "DEFAULT_MAX_EVENTS",
    "EVENT_ACTION_EXECUTED",
    "EVENT_DEVICE_CONNECTED",
    "EVENT_DEVICE_DISCONNECTED",
    "EVENT_HEALTH_CHANGED",
    "EVENT_METRIC_ALERT",
    "EVENT_RECOMMENDATION",
    "EVENT_RULE_FIRED",
    "EVENT_SESSION_STARTED",
    "EventTimeline",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "TimelineEvent",
]
