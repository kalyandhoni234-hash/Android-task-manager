"""Unit tests for the baseline diff engine.

No device required: both inputs are in-memory ``BaselineSnapshot`` fixtures.
The engine emits facts only — NEW/REMOVED structural changes, always INFO
severity — and never diffs unverified categories ("could not verify").
"""

from __future__ import annotations

from datetime import datetime, timezone

from android_task_manager.baseline.diff import diff_snapshot
from android_task_manager.baseline.models import (
    SEVERITY_INFO,
    BaselineSnapshot,
    PackageIdentity,
    ProcessRef,
    SocketIdentity,
)
from android_task_manager.baseline.snapshot import build_snapshot
from android_task_manager.network_investigation.models import NetworkInvestigationSnapshot
from android_task_manager.process.models import ProcessCategory, ProcessInfo

FIXED_CREATED_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
FIXED_COMPARED_AT = datetime(2026, 8, 15, 12, 30, 0, tzinfo=timezone.utc)


def _proc(name: str, uid: int | None = 10200) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=ProcessCategory.USER)


def _pkg(name: str, uid: int | None = 10200) -> PackageIdentity:
    return PackageIdentity(package_name=name, uid=uid)


def _sock(protocol: str = "tcp", address: str = "0.0.0.0", port: int = 8080, uid: int | None = 10200) -> SocketIdentity:
    return SocketIdentity(protocol=protocol, local_address=address, local_port=port, uid=uid)


def _snapshot(
    *,
    processes: frozenset[ProcessRef] = frozenset(),
    packages: frozenset[PackageIdentity] = frozenset(),
    sockets: frozenset[SocketIdentity] = frozenset(),
    processes_verified: bool = True,
    packages_verified: bool = True,
    sockets_verified: bool = True,
) -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=FIXED_CREATED_AT,
        device_serial="R58M1234567",
        processes=processes,
        packages=packages,
        sockets=sockets,
        processes_verified=processes_verified,
        packages_verified=packages_verified,
        sockets_verified=sockets_verified,
    )


def _run(baseline: BaselineSnapshot, current: BaselineSnapshot):
    return diff_snapshot(baseline, current, compared_at=FIXED_COMPARED_AT)


def _process_info(pid: int, name: str, uid: int | None) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name=name,
        uid=uid,
        state="S",
        cpu_percent=0.5,
        memory_percent=0.25,
        category=ProcessCategory.USER,
    )


# ---------------------------------------------------------------------------
# The 11 required cases.
# ---------------------------------------------------------------------------


def test_new_process_detected() -> None:
    report = _run(
        _snapshot(processes=frozenset({_proc("com.example.app")})),
        _snapshot(processes=frozenset({_proc("com.example.app"), _proc("com.example.new")})),
    )
    assert len(report.events) == 1
    event = report.events[0]
    assert event.category == "process"
    assert event.change_type == "NEW"
    assert event.entity == "com.example.new"
    assert event.explanation == "New process observed"
    assert event.baseline_value is None
    assert event.current_value == "com.example.new (uid 10200, user)"


def test_removed_process_detected() -> None:
    report = _run(
        _snapshot(processes=frozenset({_proc("com.example.app"), _proc("com.example.gone")})),
        _snapshot(processes=frozenset({_proc("com.example.app")})),
    )
    assert len(report.events) == 1
    event = report.events[0]
    assert event.category == "process"
    assert event.change_type == "REMOVED"
    assert event.entity == "com.example.gone"
    assert event.explanation == "Process no longer observed"
    assert event.baseline_value == "com.example.gone (uid 10200, user)"
    assert event.current_value is None


def test_pid_change_does_not_create_false_positive() -> None:
    """The single most important invariant: PIDs are never diff identities.

    A restarted process (e.g. a browser relaunching with a new PID) must
    produce zero drift events.
    """
    baseline = build_snapshot(
        "R58M1234567",
        [_process_info(111, "com.example.chrome", 10205)],
        (),
        sockets=NetworkInvestigationSnapshot(source_available=True),
        created_at=FIXED_CREATED_AT,
    )
    current = build_snapshot(
        "R58M1234567",
        [_process_info(999, "com.example.chrome", 10205)],
        (),
        sockets=NetworkInvestigationSnapshot(source_available=True),
        created_at=FIXED_CREATED_AT,
    )
    assert baseline.processes == current.processes
    report = _run(baseline, current)
    assert report.events == ()
    assert report.unverified_categories == ()


def test_new_package_detected() -> None:
    report = _run(
        _snapshot(packages=frozenset({_pkg("com.example.app")})),
        _snapshot(packages=frozenset({_pkg("com.example.app"), _pkg("com.example.installed", 10211)})),
    )
    assert len(report.events) == 1
    event = report.events[0]
    assert event.category == "package"
    assert event.change_type == "NEW"
    assert event.entity == "com.example.installed"
    assert event.explanation == "New package installed"
    assert event.current_value == "com.example.installed (uid 10211)"


def test_removed_package_detected() -> None:
    report = _run(
        _snapshot(packages=frozenset({_pkg("com.example.app"), _pkg("com.example.uninstalled")})),
        _snapshot(packages=frozenset({_pkg("com.example.app")})),
    )
    assert len(report.events) == 1
    event = report.events[0]
    assert event.category == "package"
    assert event.change_type == "REMOVED"
    assert event.entity == "com.example.uninstalled"
    assert event.explanation == "Package no longer installed"
    assert event.baseline_value == "com.example.uninstalled (uid 10200)"


def test_new_listening_socket_detected() -> None:
    report = _run(
        _snapshot(sockets=frozenset({_sock("tcp", "0.0.0.0", 4444)})),
        _snapshot(sockets=frozenset({_sock("tcp", "0.0.0.0", 4444), _sock("tcp6", "::", 5050, 1000)})),
    )
    assert len(report.events) == 1
    event = report.events[0]
    assert event.category == "socket"
    assert event.change_type == "NEW"
    # IPv6 wildcard address "::" joins honestly: tcp6 + ":" + "::" + ":" + port.
    assert event.entity == "tcp6::::5050"
    assert event.explanation == "New listening socket detected"
    assert event.current_value == "tcp6::::5050 (uid 1000)"


def test_removed_listening_socket_detected() -> None:
    report = _run(
        _snapshot(sockets=frozenset({_sock("tcp", "0.0.0.0", 4444), _sock("udp", "0.0.0.0", 5353)})),
        _snapshot(sockets=frozenset({_sock("tcp", "0.0.0.0", 4444)})),
    )
    assert len(report.events) == 1
    event = report.events[0]
    assert event.category == "socket"
    assert event.change_type == "REMOVED"
    assert event.entity == "udp:0.0.0.0:5353"
    assert event.explanation == "Listening socket no longer observed"
    assert event.baseline_value == "udp:0.0.0.0:5353 (uid 10200)"


def test_no_changes_produces_empty_report() -> None:
    report = _run(_snapshot(), _snapshot())
    assert report.events == ()
    assert report.unverified_categories == ()
    assert report.baseline_created_at == FIXED_CREATED_AT
    assert report.compared_at == FIXED_COMPARED_AT


def test_unverified_category_is_not_diffed() -> None:
    current = _snapshot(
        sockets=frozenset({_sock("tcp", "0.0.0.0", 9999)}),
        sockets_verified=False,
    )
    baseline = _snapshot(sockets=frozenset({_sock("tcp", "0.0.0.0", 4444)}))
    report = _run(baseline, current)
    assert report.events == ()
    assert report.unverified_categories == ("socket",)


def test_socket_without_uid_attribution_not_fabricated() -> None:
    baseline = _snapshot(sockets=frozenset({_sock("tcp", "0.0.0.0", 4444, None)}))
    current = _snapshot(
        sockets=frozenset({_sock("tcp", "0.0.0.0", 4444, None), _sock("udp", "0.0.0.0", 53, None)})
    )
    report = _run(baseline, current)
    assert len(report.events) == 1
    event = report.events[0]
    assert event.category == "socket"
    assert event.entity == "udp:0.0.0.0:53"
    # uid was unavailable on both sides — the value never invents one.
    assert event.current_value == "udp:0.0.0.0:53"


def test_multiple_simultaneous_changes() -> None:
    baseline = _snapshot(
        processes=frozenset({_proc("com.example.app")}),
        packages=frozenset({_pkg("com.example.app")}),
        sockets=frozenset({_sock("tcp", "0.0.0.0", 4444)}),
    )
    current = _snapshot(
        processes=frozenset({_proc("com.example.app"), _proc("com.example.newproc")}),
        packages=frozenset({_pkg("com.example.app"), _pkg("com.example.newpkg")}),
        sockets=frozenset(),
    )
    report = _run(baseline, current)
    assert len(report.events) == 3
    by_key = {(event.category, event.change_type): event for event in report.events}
    assert set(by_key) == {
        ("process", "NEW"),
        ("package", "NEW"),
        ("socket", "REMOVED"),
    }
    assert by_key[("process", "NEW")].entity == "com.example.newproc"
    assert by_key[("package", "NEW")].entity == "com.example.newpkg"
    assert by_key[("socket", "REMOVED")].entity == "tcp:0.0.0.0:4444"


# ---------------------------------------------------------------------------
# Additional edge cases.
# ---------------------------------------------------------------------------


def test_unverified_on_baseline_side_also_blocks_diffing() -> None:
    baseline = _snapshot(sockets=frozenset({_sock("tcp", "0.0.0.0", 4444)}), sockets_verified=False)
    current = _snapshot(sockets=frozenset())
    report = _run(baseline, current)
    assert report.events == ()
    assert report.unverified_categories == ("socket",)


def test_unverified_category_listed_once_when_both_sides_unverified() -> None:
    baseline = _snapshot(packages=frozenset({_pkg("com.example.app")}), packages_verified=False)
    current = _snapshot(packages=frozenset(), packages_verified=False)
    report = _run(baseline, current)
    assert report.events == ()
    assert report.unverified_categories == ("package",)


def test_unverified_processes_block_only_process_diffing() -> None:
    baseline = _snapshot(
        processes=frozenset({_proc("com.example.gone")}),
        packages=frozenset({_pkg("com.example.app")}),
        processes_verified=False,
    )
    current = _snapshot(
        processes=frozenset(),
        packages=frozenset({_pkg("com.example.app"), _pkg("com.example.newpkg")}),
        processes_verified=False,
    )
    report = _run(baseline, current)
    assert report.unverified_categories == ("process",)
    assert [(e.category, e.change_type, e.entity) for e in report.events] == [
        ("package", "NEW", "com.example.newpkg")
    ]


def test_multiple_unverified_categories_in_fixed_order() -> None:
    baseline = _snapshot(processes_verified=False, packages_verified=False, sockets_verified=False)
    current = _snapshot(processes_verified=False, packages_verified=False, sockets_verified=False)
    report = _run(baseline, current)
    assert report.unverified_categories == ("process", "package", "socket")


def test_events_are_sorted_deterministically() -> None:
    baseline = _snapshot(
        processes=frozenset({_proc("z.app"), _proc("m.app")}),
        packages=frozenset({_pkg("z.pkg")}),
        sockets=frozenset({_sock("udp", "0.0.0.0", 53), _sock("tcp", "0.0.0.0", 4444)}),
    )
    current = _snapshot(
        processes=frozenset({_proc("a.app")}),
        packages=frozenset({_pkg("a.pkg"), _pkg("z.pkg")}),
        sockets=frozenset({_sock("udp", "0.0.0.0", 53)}),
    )
    report = _run(baseline, current)
    assert [(e.category, e.change_type, e.entity) for e in report.events] == [
        # package NEW a.pkg (entity) — category, then change_type, then entity.
        ("package", "NEW", "a.pkg"),
        # process: REMOVED m.app/new z.app removed, NEW a.app.
        ("process", "NEW", "a.app"),
        ("process", "REMOVED", "m.app"),
        ("process", "REMOVED", "z.app"),
        # socket: removed.
        ("socket", "REMOVED", "tcp:0.0.0.0:4444"),
    ]


def test_severity_is_always_info() -> None:
    baseline = _snapshot(
        processes=frozenset({_proc("a")}),
        packages=frozenset({_pkg("a.pkg")}),
        sockets=frozenset({_sock("tcp", "0.0.0.0", 1)}),
    )
    current = _snapshot(
        processes=frozenset({_proc("a"), _proc("b")}),
        packages=frozenset({_pkg("a.pkg"), _pkg("b.pkg")}),
        sockets=frozenset({_sock("tcp", "0.0.0.0", 1), _sock("tcp", "0.0.0.0", 2)}),
    )
    report = _run(baseline, current)
    assert len(report.events) == 3
    assert all(event.severity == SEVERITY_INFO for event in report.events)


def test_same_process_name_with_different_uid_is_new_and_removed() -> None:
    """Name alone is not identity: a UID change is a real structural change."""
    report = _run(
        _snapshot(processes=frozenset({_proc("com.example.app", 10200)})),
        _snapshot(processes=frozenset({_proc("com.example.app", 10250)})),
    )
    assert [(e.change_type, e.entity, e.baseline_value, e.current_value) for e in report.events] == [
        ("NEW", "com.example.app", None, "com.example.app (uid 10250, user)"),
        ("REMOVED", "com.example.app", "com.example.app (uid 10200, user)", None),
    ]


def test_identical_nonempty_snapshots_produce_empty_report() -> None:
    snapshot = _snapshot(
        processes=frozenset({_proc("com.example.app")}),
        packages=frozenset({_pkg("com.example.app", 10200)}),
        sockets=frozenset({_sock("tcp", "0.0.0.0", 4444, 10200)}),
    )
    report = _run(snapshot, snapshot)
    assert report.events == ()
    assert report.unverified_categories == ()


def test_drift_event_defaults_are_stable() -> None:
    from android_task_manager.baseline.models import DriftEvent

    event = DriftEvent(category="process", change_type="NEW")
    assert event.severity == SEVERITY_INFO
    assert event.entity == ""
    assert event.baseline_value is None
    assert event.current_value is None
    assert event.explanation == ""