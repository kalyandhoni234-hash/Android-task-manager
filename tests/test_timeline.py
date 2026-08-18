"""Tests for the device event timeline (Phase C).

Covers bounded retention, deterministic ordering and ids, timestamping,
device scoping (session isolation) and meaningful-transitions-only
deduplication.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from android_task_manager.timeline import (
    DEFAULT_MAX_EVENTS,
    EVENT_DEVICE_CONNECTED,
    EVENT_DEVICE_DISCONNECTED,
    EVENT_HEALTH_CHANGED,
    EVENT_SESSION_STARTED,
    EventTimeline,
)


def _wall_clock(base: datetime, seconds: float) -> datetime:
    return base + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Bounded retention
# ---------------------------------------------------------------------------


def test_timeline_is_bounded() -> None:
    timeline = EventTimeline(max_events=5)
    for i in range(10):
        timeline.record(EVENT_DEVICE_CONNECTED, f"title {i}", f"desc {i}")
    assert len(timeline) == 5
    assert timeline[0].title == "title 5"  # oldest dropped
    assert timeline[-1].title == "title 9"


def test_default_bounds_is_256() -> None:
    assert EventTimeline().max_events == DEFAULT_MAX_EVENTS
    with pytest.raises(ValueError):
        EventTimeline(max_events=0)


def test_record_with_max_events_boundary_keeps_latest() -> None:
    timeline = EventTimeline(max_events=3)
    for i in range(3):
        timeline.record(EVENT_DEVICE_CONNECTED, f"t{i}", f"d{i}")
    timeline.record(EVENT_DEVICE_DISCONNECTED, "t3", "d3")
    assert [e.title for e in timeline] == ["t1", "t2", "t3"]


# ---------------------------------------------------------------------------
# Deterministic ordering and ids
# ---------------------------------------------------------------------------


def test_ids_are_sequential_deterministic() -> None:
    timeline = EventTimeline()
    first = timeline.record(EVENT_DEVICE_CONNECTED, "t1", "d1")
    second = timeline.record(EVENT_DEVICE_DISCONNECTED, "t2", "d2")
    assert first.event_id == "T-001"
    assert second.event_id == "T-002"


def test_ids_restart_on_clear() -> None:
    timeline = EventTimeline()
    timeline.record(EVENT_DEVICE_CONNECTED, "t1", "d1")
    timeline.clear()
    event = timeline.record(EVENT_DEVICE_CONNECTED, "t2", "d2")
    assert event.event_id == "T-001"


def test_insertion_order_is_chronological() -> None:
    timeline = EventTimeline()
    for i in range(4):
        timeline.record(EVENT_HEALTH_CHANGED, f"t{i}", f"d{i}")
    assert [e.title for e in timeline] == ["t0", "t1", "t2", "t3"]


# ---------------------------------------------------------------------------
# Timestamping
# ---------------------------------------------------------------------------


def test_timestamps_recorded_when_provided() -> None:
    timeline = EventTimeline()
    now = datetime(2026, 8, 18, 12, 0, 0)
    event = timeline.record(
        EVENT_HEALTH_CHANGED,
        "t",
        "d",
        monotonic=1234.5,
        wall_clock=now,
    )
    assert event.monotonic == 1234.5
    assert event.timestamp == now


def test_missing_clocks_are_not_fabricated() -> None:
    timeline = EventTimeline()
    event = timeline.record(EVENT_HEALTH_CHANGED, "t", "d")
    assert event.monotonic is None
    assert event.timestamp is None


def test_device_serial_and_evidence_refs_recorded() -> None:
    timeline = EventTimeline()
    event = timeline.record(
        EVENT_HEALTH_CHANGED,
        "t",
        "d",
        device_serial="FAKE123",
        entity="com.example.app",
        severity="warning",
        evidence_refs=("process:com.example.app", "T-001"),
    )
    assert event.device_serial == "FAKE123"
    assert event.entity == "com.example.app"
    assert event.severity == "warning"
    assert event.evidence_refs == ("process:com.example.app", "T-001")


# ---------------------------------------------------------------------------
# Device scoping
# ---------------------------------------------------------------------------


def test_begin_session_resets_and_records_session_started() -> None:
    timeline = EventTimeline()
    timeline.record(EVENT_DEVICE_CONNECTED, "old", "old device")
    timeline.begin_session("FAKE123", monotonic=42.0)
    events = list(timeline)
    assert len(events) == 1
    assert events[0].event_type == EVENT_SESSION_STARTED
    assert events[0].device_serial == "FAKE123"
    assert events[0].monotonic == 42.0
    assert events[0].event_id == "T-001"


def test_events_of_previous_device_never_surface() -> None:
    timeline = EventTimeline()
    timeline.begin_session("FAKE123")
    timeline.record(EVENT_HEALTH_CHANGED, "t", "d", device_serial="FAKE123")
    timeline.begin_session("FAKE456")
    assert all(event.device_serial == "FAKE456" for event in timeline)
    assert len(timeline) == 1


# ---------------------------------------------------------------------------
# Meaningful transitions only
# ---------------------------------------------------------------------------


def test_repeated_state_produces_no_event() -> None:
    timeline = EventTimeline()
    timeline.begin_session("FAKE123")
    first = timeline.record_transition(
        "health", "WARNING", EVENT_HEALTH_CHANGED, "t", "d"
    )
    assert first is not None
    repeated = timeline.record_transition(
        "health", "WARNING", EVENT_HEALTH_CHANGED, "t", "d"
    )
    assert repeated is None
    assert len(timeline) == 2  # session start + one transition


def test_state_flip_produces_exactly_one_event() -> None:
    timeline = EventTimeline()
    timeline.begin_session("FAKE123")
    timeline.record_transition("health", "HEALTHY", EVENT_HEALTH_CHANGED, "h", "d")
    changed = timeline.record_transition(
        "health", "WARNING", EVENT_HEALTH_CHANGED, "w", "d"
    )
    assert changed is not None
    flipped_back = timeline.record_transition(
        "health", "HEALTHY", EVENT_HEALTH_CHANGED, "h", "d"
    )
    assert flipped_back is not None
    events = [e for e in timeline if e.event_type == EVENT_HEALTH_CHANGED]
    assert [e.description for e in events] == ["d", "d", "d"]


def test_transitions_are_per_key() -> None:
    timeline = EventTimeline()
    timeline.begin_session("FAKE123")
    timeline.record_transition("health", "WARNING", EVENT_HEALTH_CHANGED, "h", "d")
    # A different key with the same value is a fresh transition.
    other = timeline.record_transition(
        "connectivity", "WARNING", EVENT_HEALTH_CHANGED, "c", "d"
    )
    assert other is not None


def test_transition_state_resets_on_new_session() -> None:
    timeline = EventTimeline()
    timeline.begin_session("FAKE123")
    timeline.record_transition("health", "WARNING", EVENT_HEALTH_CHANGED, "w", "d")
    timeline.begin_session("FAKE456")
    first = timeline.record_transition(
        "health", "WARNING", EVENT_HEALTH_CHANGED, "w", "d"
    )
    assert first is not None  # never suppressed across devices


def test_transition_burst_is_single_event() -> None:
    timeline = EventTimeline(max_events=64)
    timeline.begin_session("FAKE123")
    timeline.record_transition("health", "CRITICAL", EVENT_HEALTH_CHANGED, "c", "d")
    for _ in range(50):  # a polling storm repeating the same state
        timeline.record_transition("health", "CRITICAL", EVENT_HEALTH_CHANGED, "c", "d")
    assert len(timeline) == 2  # session start + one transition


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_latest_and_of_type() -> None:
    timeline = EventTimeline()
    timeline.begin_session("FAKE123")
    timeline.record(EVENT_DEVICE_CONNECTED, "connected", "d", device_serial="FAKE123")
    timeline.record(EVENT_HEALTH_CHANGED, "w", "d")
    timeline.record(EVENT_HEALTH_CHANGED, "c", "d")
    assert timeline.latest(EVENT_HEALTH_CHANGED).title == "c"
    assert timeline.latest(EVENT_DEVICE_DISCONNECTED) is None
    assert [e.title for e in timeline.of_type(EVENT_HEALTH_CHANGED)] == ["w", "c"]


def test_is_empty() -> None:
    assert EventTimeline().is_empty
    assert EventTimeline().record(EVENT_DEVICE_CONNECTED, "t", "d") is not None
