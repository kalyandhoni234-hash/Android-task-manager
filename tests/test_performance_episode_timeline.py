"""TEST-FIRST SPEC (RED) — Episode completion on the unified Timeline.

Phase 5b deliberately reused the ConditionTracker's throttled STARTED / ACTIVE
/ RECOVERED events as the episode lifecycle stream, so episodes are invisible
on the unified Timeline as *episodes*: the user sees "CPU critical
(recovered)" but never learns that incident P-001 ended, how the incident as a
whole was rated, or that the device recovered.

This module locks the desired USER-VISIBLE behavior for the next small
upgrade BEFORE implementation:

    When a grouped performance episode recovers, exactly ONE additional
    performance event is emitted through the EXISTING event pipeline
    (OrchestratorResult.events -> PerformanceIntegration.events_ready ->
    MainWindow._on_performance_events -> to_timeline_event -> EventTimeline),
    titled with the deterministic episode id and recovery, carrying the
    episode's escalated severity. No events are emitted while the episode is
    open (no flooding), ids restart after session reset, and the event adapts
    through the existing timeline adapter unchanged.

These tests intentionally FAIL until the feature is implemented (TDD red).
They assert only observable outputs of the public orchestrator/event API —
never internal tracker state. No device, sleep, or Qt is required.

Explicitly OUT of scope for the future implementation (architecture guards):
another QTimer/MonitorWorker/polling loop, duplicate ADB collection,
duplicate process/app inventory or APK resolution, destructive automatic
actions, and causal claims ("caused") — correlation wording only.
"""

from __future__ import annotations

import re

from android_task_manager.cpu.models import CPUSnapshot
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.performance import (
    PerformanceEvent,
    PerformanceOrchestrator,
    PerformanceSession,
    to_timeline_event,
)
from android_task_manager.timeline.models import (
    EVENT_METRIC_ALERT,
    SEVERITY_CRITICAL,
)

_EPISODE_ID_RE = re.compile(r"P-\d{3}")


# --------------------------------------------------------------------------
# Builders (self-contained on purpose; mirrors the established conventions)
# --------------------------------------------------------------------------

def _cpu_snap(pct, ts):
    return CPUSnapshot(timestamp=ts, aggregate_utilization_percent=pct, cores=())


def _mem_snap(pct, ts):
    total = 1000
    avail = int(round(total * (1 - pct / 100.0)))
    return MemorySnapshot(timestamp=ts, total_kb=total, free_kb=0, available_kb=avail,
                          buffers_kb=0, cached_kb=0, swap_cached_kb=0)


def _orchestrator():
    # Small bounded windows so breaches are evicted by fresh low samples,
    # matching the convention used by the Phase 5b episode tests.
    return PerformanceOrchestrator(
        session=PerformanceSession(cpu_max_samples=8, memory_max_samples=8),
    )


def _drive(orchestrator, ticks):
    """ticks: list of dicts with optional 'cpu'/'memory' percents.

    A small deterministic jitter is added because MetricHistory retains
    *changes* — a flat series collapses to one window sample (the same
    convention every earlier phase test uses).
    """
    seen = []
    for i, tick in enumerate(ticks):
        jitter = ((i % 3) - 1) * 0.5
        result = orchestrator.ingest(
            cpu=_cpu_snap(tick["cpu"] + jitter, float(i)) if "cpu" in tick else None,
            memory=_mem_snap(tick["memory"] + jitter, float(i))
            if "memory" in tick else None,
            timestamp=float(i),
        )
        seen.extend(result.events)
    return seen


_CPU_INCIDENT = [{"cpu": 95.0}] * 6 + [{"cpu": 12.0}] * 10
_MEM_INCIDENT = [{"memory": 94.0}] * 6 + [{"memory": 20.0}] * 10


def _episode_recovered_events(events):
    """User-visible contract: events announcing a specific episode's recovery."""
    return [
        ev
        for ev in events
        if isinstance(ev, PerformanceEvent)
        and "recovered" in ev.title.lower()
        and _EPISODE_ID_RE.search(ev.title)
    ]


# --------------------------------------------------------------------------
# 1. One recovered episode -> exactly one timeline-bound event
# --------------------------------------------------------------------------

def test_recovered_episode_emits_one_identifiable_event():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    events = _drive(o, _CPU_INCIDENT)

    recovered = _episode_recovered_events(events)
    assert len(recovered) == 1, (
        f"expected exactly one episode-recovery event, got {len(recovered)}"
    )
    ev = recovered[0]
    assert "P-001" in ev.title
    # The escalated episode severity is preserved (cpu >= 85% => critical).
    assert ev.severity == "critical"
    # Recovery implies the episode ran from its start to this moment.
    assert ev.timestamp >= 9.0  # after the breach window began


# --------------------------------------------------------------------------
# 2. No flooding while the episode is open
# --------------------------------------------------------------------------

def test_open_episode_emits_no_episode_events():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    events = _drive(o, [{"cpu": 95.0}] * 15)  # sustained breach, never recovers

    # The only lifecycle event is the single condition STARTED; the open
    # episode itself must stay silent (no per-tick or per-interval spam).
    assert len(events) == 1
    assert "started" in events[0].title.lower()
    assert _episode_recovered_events(events) == []


# --------------------------------------------------------------------------
# 3. Sequential incidents -> ordered, distinct recovery announcements
# --------------------------------------------------------------------------

def test_two_episodes_emit_ordered_recovery_events():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    events = _drive(o, _CPU_INCIDENT + _MEM_INCIDENT)

    recovered = _episode_recovered_events(events)
    ids = [_EPISODE_ID_RE.search(ev.title).group(0) for ev in recovered]
    assert ids == ["P-001", "P-002"]
    # Deterministic chronological order, one announcement per incident.
    assert recovered[0].timestamp <= recovered[1].timestamp


# --------------------------------------------------------------------------
# 4. The announcement adapts through the EXISTING timeline adapter
# --------------------------------------------------------------------------

def test_recovery_event_flows_through_existing_timeline_adapter():
    o = _orchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    events = _drive(o, _CPU_INCIDENT)

    (ev,) = _episode_recovered_events(events)
    tl = to_timeline_event(ev, event_id="T-000", device_serial="SERIAL")
    assert tl.event_type == EVENT_METRIC_ALERT
    assert tl.severity == SEVERITY_CRITICAL
    assert tl.monotonic == ev.timestamp
    assert "P-001" in tl.title
    # The episode id travels as identity vocabulary, never embedded metrics.
    assert "P-001" in tl.evidence_refs


# --------------------------------------------------------------------------
# 5. Session reset restarts the announced ids (no stale resurrection)
# --------------------------------------------------------------------------

def test_announced_ids_restart_after_session_reset():
    o = _orchestrator()
    o.begin_session("A", timestamp=0.0)
    first = _episode_recovered_events(_drive(o, _CPU_INCIDENT))
    assert [_EPISODE_ID_RE.search(ev.title).group(0) for ev in first] == ["P-001"]

    o.end_session()
    o.begin_session("B", timestamp=1000.0)
    second = _episode_recovered_events(_drive(o, _MEM_INCIDENT))
    assert [_EPISODE_ID_RE.search(ev.title).group(0) for ev in second] == ["P-001"]
