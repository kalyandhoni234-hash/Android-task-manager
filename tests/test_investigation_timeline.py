"""Investigation timeline & correlation tests.

No device required. Verifies deterministic ordering, stable event ids,
the drift-event/transient/uncertain buckets, the source event types,
and non-causal entity correlation.
"""

from __future__ import annotations

from android_task_manager.baseline.models import (
    CATEGORY_PROCESS,
    CHANGE_NEW,
    CHANGE_REMOVED,
)
from android_task_manager.investigation.models import (
    EVENT_BASELINE_CREATED,
    EVENT_DRIFT_CHECKED,
    EVENT_DRIFT_EVENT,
    EVENT_HEURISTICS_EVALUATED,
    EVENT_NOT_OBSERVED,
    EVENT_PERMISSION_AUDITED,
    EVENT_SIGNAL_GENERATED,
    EVENT_TRANSIENT_CHANGE,
    RELATION_OWNED_BY,
)
from android_task_manager.investigation.stability import stabilize_drift
from android_task_manager.investigation.timeline import (
    build_investigation_timeline,
    correlate_entity,
)
from tests import investigation_fixtures as fx


def _timeline_with(stability=None, session=None, **kwargs):
    session = session or fx.make_session(
        fx.baseline_with_stable(),
        fx.current_with_new_process(),
        (fx.drift_event(CATEGORY_PROCESS, CHANGE_NEW, fx.NEW_PROC.process_name),),
    )
    return build_investigation_timeline(
        session=session, stability=stability, **kwargs
    )


def test_timeline_is_deterministic() -> None:
    first = _timeline_with()
    second = _timeline_with()
    assert first == second
    assert [(e.event_id, e.event_type, e.description) for e in first] == [
        (e.event_id, e.event_type, e.description) for e in second
    ]


def test_event_ids_assigned_after_sorting() -> None:
    events = _timeline_with()
    assert [e.event_id for e in events] == [f"T-{i:03d}" for i in range(1, len(events) + 1)]


def test_drift_events_carry_entity_and_evidence_ref() -> None:
    events = _timeline_with()
    drift = [e for e in events if e.event_type == EVENT_DRIFT_EVENT]
    assert len(drift) == 1
    assert drift[0].entity == fx.NEW_PROC.process_name
    assert drift[0].evidence_refs == (fx.NEW_PROC.process_name,)
    assert drift[0].severity == "INFO"


def test_transient_change_gets_dedicated_event_type() -> None:
    report = fx.new_process_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.current_with_new_process(),
        series=fx.transient_series(),
    )
    events = _timeline_with(stability=stability)
    transient = [e for e in events if e.event_type == EVENT_TRANSIENT_CHANGE]
    assert len(transient) == 1
    assert transient[0].entity == fx.NEW_PROC.process_name
    assert "not" in transient[0].description.lower() or "non-persistent" in transient[0].description.lower()


def test_uncertain_change_gets_not_observed_event_type() -> None:
    report = fx.removed_process_report()
    current = fx.snapshot(
        fx.ts("2026-01-01T10:00:05Z"),
        processes=(fx.STABLE_A,),
        processes_verified=False,
    )
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        current,
        series=fx.uncertain_series(),
    )
    session = fx.make_session(
        fx.baseline_with_stable(),
        current,
        report.events,
    )
    events = _timeline_with(stability=stability, session=session)
    unconfirmed = [e for e in events if e.event_type == EVENT_NOT_OBSERVED]
    assert len(unconfirmed) == 1
    assert unconfirmed[0].entity == fx.STABLE_APP.process_name


def test_source_event_types_present() -> None:
    session = fx.make_session(
        fx.baseline_with_stable(),
        fx.current_with_new_process(),
        (fx.drift_event(CATEGORY_PROCESS, CHANGE_NEW, fx.NEW_PROC.process_name),),
    )
    heuristics = fx.heuristic_report(
        ("RULE_A",),
        (fx.signal("RULE_A", "MEDIUM", fx.NEW_PROC.process_name, "reason"),),
        fx.ts("2026-01-01T10:00:06Z"),
    )
    events = build_investigation_timeline(
        session=session,
        heuristics=heuristics,
        audits=(),
    )
    types = {e.event_type for e in events}
    assert EVENT_BASELINE_CREATED in types
    assert EVENT_DRIFT_CHECKED in types
    assert EVENT_HEURISTICS_EVALUATED in types
    assert EVENT_SIGNAL_GENERATED in types
    assert EVENT_DRIFT_EVENT in types


def test_timeline_never_fabricates_timestamps() -> None:
    events = _timeline_with()
    assert all(e.timestamp is not None for e in events)
    assert events[0].timestamp == fx.ts("2026-01-01T10:00:00Z")


def test_correlate_entity_socket_owned_by_process() -> None:
    current = fx.snapshot(
        fx.ts("2026-01-01T10:00:05Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP, fx.NEW_PROC),
        sockets=(fx.STABLE_SOCK, fx.NEW_SOCK),
    )
    relations = correlate_entity(
        "tcp:0.0.0.0:4444",
        current=current,
    )
    # The socket is owned by uid 10200 — the new process's UID — so the
    # relationship is OWNED_BY, never a causal claim.
    assert relations.relation == RELATION_OWNED_BY
    assert fx.NEW_PROC in relations.processes
    assert fx.NEW_SOCK in relations.sockets