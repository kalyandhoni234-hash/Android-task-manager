"""End-to-end investigation integration — one fixture-driven story.

No device required. The scenario: a new package is installed, its new
process starts listening on a new socket, and the existing heuristic
layer raises a HIGH signal. The test drives that story through every
investigation feature — stability, timeline, attribution, process tree,
why-flagged evidence and the incident report — and asserts the artifacts
agree with each other.
"""

from __future__ import annotations

from datetime import datetime, timezone

from android_task_manager.baseline.models import (
    CATEGORY_PACKAGE,
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
    CHANGE_NEW,
)
from android_task_manager.heuristics.evaluate import evaluate_heuristics
from android_task_manager.incident.builder import build_incident_report
from android_task_manager.incident.models import (
    EVENT_TRANSIENT_CHANGE,
    SCHEMA_VERSION,
)
from android_task_manager.investigation.attribution import attribute_sockets
from android_task_manager.investigation.explain import entity_stability_for, explain_signal
from android_task_manager.investigation.models import (
    EVENT_DRIFT_EVENT,
    EVENT_STABILITY_ANALYZED,
    ObservationState,
)
from android_task_manager.investigation.stability import stabilize_drift
from android_task_manager.investigation.timeline import build_investigation_timeline
from android_task_manager.investigation.tree import build_process_tree
from android_task_manager.process.models import ProcessCategory
from tests import investigation_fixtures as fx

PKG = "com.example.trojan"
UID = 10666
PROCESS = fx.process(UID, PKG, ProcessCategory.USER)
SOCKET = fx.socket("tcp", "0.0.0.0", 4444, uid=UID)
SOCKET2 = fx.socket("udp", "0.0.0.0", 5353, uid=UID)
EVENT_TIME = fx.ts("2026-01-01T10:00:05Z")


def _story_baseline() -> fx.BaselineSnapshot:
    return fx.snapshot(
        fx.ts("2026-01-01T10:00:00Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
        sockets=(fx.STABLE_SOCK,),
    )


def _story_current() -> fx.BaselineSnapshot:
    return fx.snapshot(
        EVENT_TIME,
        processes=(fx.STABLE_A, fx.STABLE_APP, PROCESS),
        packages=(fx.package(PKG, UID),),
        sockets=(fx.STABLE_SOCK, SOCKET, SOCKET2),
    )


def _story_report(baseline, current):
    return fx.drift_report(
        baseline,
        current,
        (
            fx.drift_event(CATEGORY_PACKAGE, CHANGE_NEW, PKG),
            fx.drift_event(CATEGORY_PROCESS, CHANGE_NEW, PKG),
            fx.drift_event(CATEGORY_SOCKET, CHANGE_NEW, "tcp:0.0.0.0:4444"),
            fx.drift_event(CATEGORY_SOCKET, CHANGE_NEW, "udp:0.0.0.0:5353"),
        ),
    )


def _story_series():
    return {
        CATEGORY_PROCESS: (
            fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_A, fx.STABLE_APP), 100.0),
            fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_A, fx.STABLE_APP, PROCESS), 101.0),
            fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_A, fx.STABLE_APP, PROCESS), 102.0),
        ),
        CATEGORY_SOCKET: (
            fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_SOCK,), 100.0),
            fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_SOCK, SOCKET, SOCKET2), 101.0),
            fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_SOCK, SOCKET, SOCKET2), 102.0),
        ),
    }


def _story_network():
    return fx.network_snapshot(
        1.0,
        (
            fx.socket_info("tcp", "0.0.0.0", 4444, state="LISTEN", uid=UID, pid=18472),
            fx.socket_info("udp", "0.0.0.0", 5353, state="LISTEN", uid=UID, pid=18472),
        ),
        uid_packages={UID: (PKG,)},
    )


def _story_processes():
    return fx.process_snapshot(
        1000.0,
        (
            fx.process_info(1, "init", 0, ppid=0),
            fx.process_info(754, "system_server", 1000, ppid=1),
            fx.process_info(
                18472, PKG, UID, ppid=754, cpu_percent=3.5, memory_percent=1.0,
            ),
        ),
    )


def test_full_story_new_package_process_socket() -> None:
    baseline = _story_baseline()
    current = _story_current()
    drift = _story_report(baseline, current)
    heuristics = evaluate_heuristics(drift, baseline, current, evaluated_at=EVENT_TIME)

    # --- 1. Stability: the new process/sockets persist -------------------
    stability = stabilize_drift(drift, baseline, current, series=_story_series())
    assert any(
        event.change_type == CHANGE_NEW and event.entity == PKG
        for event in stability[CATEGORY_PROCESS].meaningful_events
    )
    assert any(
        event.entity == "tcp:0.0.0.0:4444"
        for event in stability[CATEGORY_SOCKET].meaningful_events
    )
    proc_record = next(
        e for e in stability[CATEGORY_PROCESS].entities if e.identity_key == PKG
    )
    assert proc_record.state is ObservationState.PERSISTENT

    # --- 2. Timeline: every phase appears, deterministically -------------
    session = fx.make_session(baseline, current, drift.events)
    timeline = build_investigation_timeline(
        session=session,
        heuristics=heuristics,
        stability=stability,
    )
    types = [e.event_type for e in timeline]
    assert EVENT_DRIFT_EVENT in types
    assert EVENT_STABILITY_ANALYZED in types
    assert "T-001" == timeline[0].event_id
    drift_events = [e for e in timeline if e.event_type == EVENT_DRIFT_EVENT]
    assert {e.entity for e in drift_events} == {PKG, "tcp:0.0.0.0:4444", "udp:0.0.0.0:5353"}
    signal_events = [e for e in timeline if e.event_type == "SIGNAL_GENERATED"]
    assert any(e.severity == "HIGH" for e in signal_events)
    assert any(e.severity == "MEDIUM" for e in signal_events)

    # --- 3. Attribution: socket → PID → process → package ----------------
    processes = _story_processes()
    attributed = attribute_sockets(
        (SOCKET, SOCKET2),
        pid_by_entity={
            "tcp:0.0.0.0:4444": 18472,
            "udp:0.0.0.0:5353": 18472,
        },
        processes=processes,
        uid_packages={UID: (PKG,)},
        baseline=baseline,
        current=current,
    )
    assert len(attributed) == 2
    # Deterministic order: tcp before udp.
    assert attributed[0].socket.protocol == "tcp"
    assert attributed[0].process_name == PKG
    assert attributed[0].package_names == (PKG,)
    assert attributed[0].uid == UID

    # --- 4. Process tree: the new process hangs under system_server ------
    tree = build_process_tree(processes)
    assert any(node.name == PKG and node.ppid == 754 for node in tree.nodes)
    assert 18472 in {node.pid for node in tree.nodes}

    # --- 5. Why-flagged: evidence facts for the MEDIUM signal ------------
    signal = next(
        s for s in heuristics.signals
        if s.rule_id == "NEW_PROCESS_WITH_ACTIVE_SOCKET"
    )
    records = [record for r in stability.values() for record in r.entities]
    explanation = explain_signal(
        signal,
        baseline=baseline,
        current=current,
        drift=drift,
        processes=processes,
        network_investigation=_story_network(),
        attribution=attributed[0],
        entity_stability=entity_stability_for(PKG, records),
    )
    fact_texts = " ".join(f.text for f in explanation.facts)
    assert "PID: 18472" in fact_texts
    assert "Socket is listening" in fact_texts
    assert PKG in fact_texts
    assert "MEDIUM" in fact_texts
    # Facts only — never a verdict.
    assert "malware" not in fact_texts.lower()
    assert "hacked" not in fact_texts.lower()

    # --- 6. Incident report consumes the investigation -------------------
    report = build_incident_report(
        session=session,
        heuristics=heuristics,
        stability=tuple(stability.values()),
        network_investigation=_story_network(),
        process_snapshot=processes,
        generated_at=datetime(2026, 1, 1, 10, 0, 10, tzinfo=timezone.utc),
    )
    assert report.schema_version == SCHEMA_VERSION
    assert report.investigation is not None
    assert report.investigation.meaningful_drift_count >= 2
    assert report.investigation.transient_drift_count == 0
    # The HIGH signal finding is present.
    assert any(f.severity == "HIGH" for f in report.findings)
    # All three meaningful drift facts became findings (package passes
    # through, process and sockets confirmed).
    assert any(f.entity == PKG for f in report.findings)
    assert any(f.entity == "tcp:0.0.0.0:4444" for f in report.findings)
    assert any(f.entity == "udp:0.0.0.0:5353" for f in report.findings)
    # Timeline contains no transient events in this confirmed story.
    assert not any(e.event_type == EVENT_TRANSIENT_CHANGE for e in report.timeline)


def test_transient_story_stays_out_of_findings() -> None:
    """A new process seen once and gone: timeline shows it, findings don't."""
    baseline = _story_baseline()
    current = _story_current()
    drift = _story_report(baseline, current)
    stability = stabilize_drift(
        drift,
        baseline,
        current,
        series={
            CATEGORY_PROCESS: (
                fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_A, fx.STABLE_APP), 100.0),
                fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_A, fx.STABLE_APP, PROCESS), 101.0),
                fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_A, fx.STABLE_APP), 102.0),
            ),
            CATEGORY_SOCKET: (
                fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_SOCK,), 100.0),
                fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_SOCK,), 101.0),
                fx.obs(fx.SnapshotCompleteness.COMPLETE, (fx.STABLE_SOCK,), 102.0),
            ),
        },
    )
    session = fx.make_session(baseline, current, drift.events)
    report = build_incident_report(
        session=session,
        stability=tuple(stability.values()),
        generated_at=datetime(2026, 1, 1, 10, 0, 10, tzinfo=timezone.utc),
    )
    assert report.investigation is not None
    assert report.investigation.transient_drift_count >= 1
    assert any(e.event_type == EVENT_TRANSIENT_CHANGE for e in report.timeline)
    # The transient process change is NOT a finding; the package fact is.
    assert not any(
        f.entity == PKG and f.category == CATEGORY_PROCESS for f in report.findings
    )
    assert any(
        f.entity == PKG and f.category == CATEGORY_PACKAGE for f in report.findings
    )