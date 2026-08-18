"""Device event timeline — bounded, ordered, deduplicating engine.

The timeline is per-session and per-device:

* **bounded** — a fixed maximum number of events; the oldest are dropped;
* **ordered** — events keep insertion order and get deterministic ``T-###``
  ids (assigned at insert, which is the ordering — like the investigation
  timeline template);
* **timestamped** — wall clock and monotonic clock are recorded when the
  caller provides them; a missing clock is never fabricated;
* **device-specific** — starting a session (re)sets the timeline so events
  of two devices never mix;
* **meaningful transitions only** — ``record_transition`` suppresses events
  that repeat the last recorded state for the same key; a state flip is
  one event, not a per-polling-cycle burst.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Iterator

from .models import EVENT_SESSION_STARTED, TimelineEvent

#: Default maximum number of events retained on the timeline. Bounded
#: growth: a busy device cannot grow the log forever.
DEFAULT_MAX_EVENTS = 256

#: Minimum id width — the investigation template ids ("T-001") style.
_ID_WIDTH = 3


@dataclass(frozen=True)
class _LastState:
    """The last recorded transition state for one key."""

    value: object


class EventTimeline:
    """A bounded, per-session, ordered device event log."""

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        if max_events < 1:
            raise ValueError("max_events must be >= 1")
        self._max_events = max_events
        self._events: Deque[TimelineEvent] = deque(maxlen=max_events)
        self._next_id = 1
        self._last_states: dict[str, _LastState] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def begin_session(self, device_serial: str | None, monotonic: float | None = None) -> None:
        """Start a session for *device_serial*.

        Resets the timeline and its transition state: events of a previous
        device must never surface as current, and the first observation of
        a state after a (re)connect is always a fresh transition.
        """
        self.clear()
        self.record(
            EVENT_SESSION_STARTED,
            "Session started",
            "Monitoring session started for the device.",
            monotonic=monotonic,
            device_serial=device_serial,
        )

    def clear(self) -> None:
        """Drop every event and reset the id sequence and transition state."""
        self._events.clear()
        self._next_id = 1
        self._last_states = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        event_type: str,
        title: str,
        description: str,
        *,
        monotonic: float | None = None,
        wall_clock: datetime | None = None,
        device_serial: str | None = None,
        severity: str | None = None,
        entity: str | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> TimelineEvent:
        """Append one event with the next deterministic ``T-###`` id."""
        event = TimelineEvent(
            event_id=f"T-{self._next_id:0{_ID_WIDTH}d}",
            event_type=event_type,
            title=title,
            description=description,
            timestamp=wall_clock,
            monotonic=monotonic,
            device_serial=device_serial,
            severity=severity,
            entity=entity,
            evidence_refs=tuple(evidence_refs),
        )
        self._events.append(event)
        self._next_id += 1
        return event

    def record_transition(
        self,
        key: str,
        value: object,
        event_type: str,
        title: str,
        description: str,
        *,
        monotonic: float | None = None,
        wall_clock: datetime | None = None,
        device_serial: str | None = None,
        severity: str | None = None,
        entity: str | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> TimelineEvent | None:
        """Record an event only when *value* differs from the last recorded
        value for *key* (a meaningful state transition).

        Repeated observations of the same state produce no event; a state
        flip always produces exactly one. Returns the event, or ``None``
        when the transition was suppressed as a duplicate.
        """
        last = self._last_states.get(key)
        if last is not None and last.value == value:
            return None
        self._last_states[key] = _LastState(value)
        return self.record(
            event_type,
            title,
            description,
            monotonic=monotonic,
            wall_clock=wall_clock,
            device_serial=device_serial,
            severity=severity,
            entity=entity,
            evidence_refs=evidence_refs,
        )

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    @property
    def max_events(self) -> int:
        return self._max_events

    @property
    def is_empty(self) -> bool:
        return not self._events

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[TimelineEvent]:
        return iter(tuple(self._events))

    def __getitem__(self, index: int) -> TimelineEvent:
        return tuple(self._events)[index]

    @property
    def events(self) -> tuple[TimelineEvent, ...]:
        """All retained events, oldest first."""
        return tuple(self._events)

    def latest(self, event_type: str) -> TimelineEvent | None:
        """The most recent event of *event_type*, or None."""
        for event in reversed(tuple(self._events)):
            if event.event_type == event_type:
                return event
        return None

    def of_type(self, event_type: str) -> tuple[TimelineEvent, ...]:
        """Retained events of *event_type*, oldest first."""
        return tuple(event for event in self._events if event.event_type == event_type)


__all__ = [
    "DEFAULT_MAX_EVENTS",
    "EventTimeline",
]
