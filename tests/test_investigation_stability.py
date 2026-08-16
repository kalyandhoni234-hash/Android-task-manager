"""Stability & drift tests — the noise-resistant detection core.

No device required. Verifies that snapshot completeness is honored
(PARTIAL/FAILED reads can never create false removals), that transient
and persistent change are distinguishable, that removals require
consecutive COMPLETE reads, that package facts pass through unstabilized,
and that the observation tracker is bounded and deduped.
"""

from __future__ import annotations

from android_task_manager.baseline.models import (
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
    CHANGE_NEW,
    CHANGE_REMOVED,
)
from android_task_manager.investigation.completeness import (
    baseline_category_completeness,
    snapshot_completeness,
    socket_table_completeness,
)
from android_task_manager.investigation.models import (
    ObservationState,
    SnapshotCompleteness,
)
from android_task_manager.investigation.stability import (
    MIN_PERSISTENT_OBSERVATIONS,
    ObservationTracker,
    classify_entity_state,
    stabilize_drift,
)
from android_task_manager.process.models import ProcessCategory
from tests import investigation_fixtures as fx

# ---------------------------------------------------------------------------
# Completeness mapping
# ---------------------------------------------------------------------------


def test_verified_read_is_complete() -> None:
    assert snapshot_completeness(verified=True, has_items=True) is SnapshotCompleteness.COMPLETE
    assert snapshot_completeness(verified=True, has_items=False) is SnapshotCompleteness.COMPLETE


def test_unverified_with_items_is_partial() -> None:
    current = fx.snapshot(
        fx.ts("2026-01-01T10:00:05Z"),
        processes=(fx.STABLE_A,),
        processes_verified=False,
    )
    assert baseline_category_completeness(current, CATEGORY_PROCESS) is SnapshotCompleteness.PARTIAL
    assert socket_table_completeness(
        fx.network_snapshot(
            1.0,
            (fx.socket_info("tcp", "0.0.0.0", 1),),
            source_available=False,
        )
    ) is SnapshotCompleteness.PARTIAL


def test_unverified_empty_is_failed() -> None:
    current = fx.snapshot(
        fx.ts("2026-01-01T10:00:05Z"),
        processes=(),
        processes_verified=False,
    )
    assert baseline_category_completeness(current, CATEGORY_PROCESS) is SnapshotCompleteness.FAILED
    assert socket_table_completeness(
        fx.network_snapshot(1.0, (), source_available=False)
    ) is SnapshotCompleteness.FAILED


def test_socket_table_available_is_complete() -> None:
    assert socket_table_completeness(
        fx.network_snapshot(1.0, (fx.socket_info("tcp", "0.0.0.0", 1),))
    ) is SnapshotCompleteness.COMPLETE


# ---------------------------------------------------------------------------
# False-removal protection (the incident-report root cause)
# ---------------------------------------------------------------------------


def test_partial_snapshot_never_confirms_removal() -> None:
    report = fx.removed_process_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.snapshot(
            fx.ts("2026-01-01T10:00:05Z"),
            processes=(fx.STABLE_A,),
            processes_verified=False,
        ),
        series=fx.uncertain_series(),
    )
    proc = stability[CATEGORY_PROCESS]
    assert not proc.meaningful_events
    assert proc.uncertain_events
    assert any(
        e.state is ObservationState.UNCERTAIN for e in proc.entities
    )


def test_failed_snapshot_never_confirms_removal() -> None:
    report = fx.removed_process_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.snapshot(
            fx.ts("2026-01-01T10:00:05Z"),
            processes=(),
            processes_verified=False,
        ),
        series=fx.failed_series(),
    )
    proc = stability[CATEGORY_PROCESS]
    assert not proc.meaningful_events
    assert proc.uncertain_events


def test_removal_requires_two_complete_absences() -> None:
    report = fx.removed_process_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.snapshot(fx.ts("2026-01-01T10:00:05Z"), processes=(fx.STABLE_A,)),
        series=fx.confirmed_removal_series(),
    )
    proc = stability[CATEGORY_PROCESS]
    assert len(proc.meaningful_events) == 1
    event = proc.meaningful_events[0]
    assert event.change_type == CHANGE_REMOVED
    assert any(e.state is ObservationState.REMOVED for e in proc.entities)


def test_single_absence_is_not_yet_removed() -> None:
    """One COMPLETE absence (plus the appended check read) is below the
    threshold when the minimum is raised — absence stays transient."""
    report = fx.removed_process_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.snapshot(fx.ts("2026-01-01T10:00:05Z"), processes=(fx.STABLE_A,)),
        series=fx.single_absence_series(),
        persistent_observations=3,
    )
    proc = stability[CATEGORY_PROCESS]
    assert not proc.meaningful_events
    assert proc.transient_events


# ---------------------------------------------------------------------------
# Transient vs persistent
# ---------------------------------------------------------------------------


def test_persistent_new_process_is_meaningful() -> None:
    report = fx.new_process_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.current_with_new_process(),
        series=fx.persistent_series(),
    )
    proc = stability[CATEGORY_PROCESS]
    assert len(proc.meaningful_events) == 1
    event = proc.meaningful_events[0]
    assert event.change_type == CHANGE_NEW
    assert event.entity == fx.NEW_PROC.process_name
    record = next(
        e for e in proc.entities if e.identity_key == fx.NEW_PROC.process_name
    )
    assert record.state is ObservationState.PERSISTENT
    # Counted across the window plus the appended check observation.
    assert record.observation_count >= MIN_PERSISTENT_OBSERVATIONS


def test_transient_new_process_is_not_meaningful() -> None:
    report = fx.new_process_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.current_with_new_process(),
        series=fx.transient_series(),
    )
    proc = stability[CATEGORY_PROCESS]
    assert not proc.meaningful_events
    assert len(proc.transient_events) == 1
    record = next(
        e for e in proc.entities if e.identity_key == fx.NEW_PROC.process_name
    )
    assert record.state is ObservationState.TRANSIENT


def test_persistent_socket_is_meaningful() -> None:
    report = fx.new_socket_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.snapshot(
            fx.ts("2026-01-01T10:00:05Z"),
            processes=(fx.STABLE_A, fx.STABLE_APP),
            sockets=(fx.STABLE_SOCK, fx.NEW_SOCK),
        ),
        series={
            CATEGORY_PROCESS: (
                fx.obs(SnapshotCompleteness.COMPLETE, (fx.STABLE_A, fx.STABLE_APP), 100.0),
                fx.obs(SnapshotCompleteness.COMPLETE, (fx.STABLE_A, fx.STABLE_APP), 101.0),
            ),
            CATEGORY_SOCKET: (
                fx.obs(SnapshotCompleteness.COMPLETE, (fx.STABLE_SOCK,), 100.0),
                fx.obs(SnapshotCompleteness.COMPLETE, (fx.STABLE_SOCK, fx.NEW_SOCK), 101.0),
                fx.obs(SnapshotCompleteness.COMPLETE, (fx.STABLE_SOCK, fx.NEW_SOCK), 102.0),
            ),
        },
    )
    sock = stability[CATEGORY_SOCKET]
    assert len(sock.meaningful_events) == 1
    assert sock.meaningful_events[0].entity == "tcp:0.0.0.0:4444"


def test_stable_identity_generates_no_event() -> None:
    report = fx.new_process_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.current_with_new_process(),
        series=fx.persistent_series(),
    )
    record = next(
        e for e in stability[CATEGORY_PROCESS].entities
        if e.identity_key == fx.STABLE_APP.process_name
    )
    assert record.state is ObservationState.STABLE
    assert fx.STABLE_APP.process_name not in {
        e.entity for e in stability[CATEGORY_PROCESS].events
    }


# ---------------------------------------------------------------------------
# Package pass-through + summaries
# ---------------------------------------------------------------------------


def test_package_events_pass_through_as_meaningful() -> None:
    report = fx.package_pass_through_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.snapshot(
            fx.ts("2026-01-01T10:00:05Z"),
            processes=(fx.STABLE_A, fx.STABLE_APP),
            packages=(fx.package("com.example.newpkg", 10500),),
            sockets=(fx.STABLE_SOCK,),
        ),
        series=fx.persistent_series(),
    )
    # Package drift is a structural fact: the package report carries the
    # raw event as meaningful without any stability classification.
    pkg = stability["package"]
    assert len(pkg.meaningful_events) == 1
    assert pkg.meaningful_events[0].entity == "com.example.newpkg"
    assert pkg.entities == ()


def test_stability_summary_reflects_buckets() -> None:
    report = fx.new_process_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.current_with_new_process(),
        series=fx.transient_series(),
    )
    summary = stability[CATEGORY_PROCESS].summary
    assert "non-persistent" in summary
    assert str(len(stability[CATEGORY_PROCESS].transient_events)) in summary


# ---------------------------------------------------------------------------
# Observation tracker
# ---------------------------------------------------------------------------


def test_tracker_dedupes_same_timestamp() -> None:
    tracker = ObservationTracker()
    tracker.record(CATEGORY_PROCESS, SnapshotCompleteness.COMPLETE, (fx.STABLE_A,), timestamp=1.0)
    tracker.record(CATEGORY_PROCESS, SnapshotCompleteness.COMPLETE, (fx.STABLE_A,), timestamp=1.0)
    assert len(tracker.series(CATEGORY_PROCESS)) == 1


def test_tracker_excludes_placeholder_rows() -> None:
    snapshot = fx.process_snapshot(
        1.0,
        (
            fx.process_info(1, "init", 0, category=ProcessCategory.SYSTEM),
            fx.process_info(99, "<pid 99>", None),
        ),
    )
    tracker = ObservationTracker()
    tracker.record_process_snapshot(snapshot)
    series = tracker.series(CATEGORY_PROCESS)
    assert len(series) == 1
    assert all(i.process_name != "<pid 99>" for i in series[0].identities)


def test_tracker_window_is_bounded() -> None:
    tracker = ObservationTracker(window=3)
    for index in range(10):
        tracker.record(CATEGORY_PROCESS, SnapshotCompleteness.COMPLETE, (fx.STABLE_A,), timestamp=float(index))
    assert len(tracker.series(CATEGORY_PROCESS)) == 3
    assert tracker.series(CATEGORY_PROCESS)[-1].timestamp == 9.0


def test_classify_requires_minimum_observations() -> None:
    state = classify_entity_state(
        fx.NEW_PROC,
        identity_in_baseline=False,
        series=(
            fx.obs(SnapshotCompleteness.COMPLETE, (fx.STABLE_A,)),
            fx.obs(SnapshotCompleteness.COMPLETE, (fx.STABLE_A, fx.NEW_PROC)),
        ),
    )
    assert state is ObservationState.TRANSIENT  # one observation < minimum
    assert MIN_PERSISTENT_OBSERVATIONS == 2