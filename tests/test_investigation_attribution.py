"""Network → process → package attribution tests.

No device required. Verifies the FULL / PARTIAL / UNAVAILABLE honesty
states: FULL only when the whole chain resolves with agreeing UIDs,
UID-level attribution never labeled package-level, and deterministic
ordering of multi-socket attribution.
"""

from __future__ import annotations

from android_task_manager.baseline.models import CHANGE_NEW, CHANGE_REMOVED
from android_task_manager.investigation.attribution import (
    attribute_socket,
    attribute_sockets,
)
from android_task_manager.investigation.models import AttributionState
from tests import investigation_fixtures as fx


def _current_with_socket(socket=None):
    return fx.snapshot(
        fx.ts("2026-01-01T10:00:05Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
        sockets=(socket or fx.NEW_SOCK,),
    )


def test_full_attribution_pid_process_package() -> None:
    current = _current_with_socket()
    processes = fx.process_snapshot(
        1.0,
        (
            fx.process_info(
                18472, "com.example.newproc", 10200, state="S",
                cpu_percent=1.0, memory_percent=0.5,
            ),
        ),
    )
    result = attribute_socket(
        fx.NEW_SOCK,
        pid=18472,
        processes=processes,
        uid_packages={10200: ("com.example.newproc",)},
        baseline=fx.baseline_with_stable(),
        current=current,
    )
    assert result.attribution_state is AttributionState.FULL
    assert result.pid == 18472
    assert result.process_name == "com.example.newproc"
    assert result.uid == 10200
    assert result.package_names == ("com.example.newproc",)
    assert result.baseline_status == CHANGE_NEW


def test_process_level_attribution_without_packages_is_partial() -> None:
    processes = fx.process_snapshot(
        1.0,
        (fx.process_info(18472, "com.example.newproc", 10200),),
    )
    result = attribute_socket(
        fx.NEW_SOCK,
        pid=18472,
        processes=processes,
        baseline=fx.baseline_with_stable(),
        current=_current_with_socket(),
    )
    assert result.attribution_state is AttributionState.PARTIAL
    assert result.process_name == "com.example.newproc"
    assert result.package_names == ()


def test_uid_only_attribution_is_partial() -> None:
    result = attribute_socket(
        fx.NEW_SOCK,
        uid_packages={10200: ("com.example.newproc",)},
        baseline=fx.baseline_with_stable(),
        current=_current_with_socket(),
    )
    assert result.attribution_state is AttributionState.PARTIAL
    assert result.pid is None
    assert result.process_name is None
    # UID-level attribution carries the UID's packages, but is never
    # labeled package-level.
    assert result.package_names == ("com.example.newproc",)


def test_uid_conflict_prevents_full() -> None:
    processes = fx.process_snapshot(
        1.0,
        (fx.process_info(18472, "com.example.other", 10999),),
    )
    result = attribute_socket(
        fx.NEW_SOCK,
        pid=18472,
        processes=processes,
        uid_packages={10200: ("com.example.newproc",)},
        baseline=fx.baseline_with_stable(),
        current=_current_with_socket(),
    )
    # The process row's UID disagrees with the socket table's UID — the
    # chain must not be called FULL; UID-level attribution stands.
    assert result.attribution_state is AttributionState.PARTIAL
    assert result.process_name is None
    assert result.uid == 10200


def test_no_data_is_unavailable() -> None:
    # A socket without any UID and no process row: no owner was collected.
    result = attribute_socket(fx.socket("tcp", "0.0.0.0", 4444, uid=None))
    assert result.attribution_state is AttributionState.UNAVAILABLE
    assert result.uid is None
    assert result.package_names == ()


def test_unknown_uid_socket_with_process_is_partial() -> None:
    # The process row identifies the socket (process-level attribution)
    # even though the socket table carried no UID.
    unknown = fx.socket("tcp", "0.0.0.0", 5555, uid=None)
    processes = fx.process_snapshot(
        1.0,
        (fx.process_info(1, "init", 0),),
    )
    result = attribute_socket(
        unknown, pid=1, processes=processes,
        baseline=fx.baseline_with_stable(),
        current=_current_with_socket(unknown),
    )
    assert result.attribution_state is AttributionState.PARTIAL
    assert result.process_name == "init"


def test_current_snapshot_packages_as_fallback() -> None:
    current = fx.snapshot(
        fx.ts("2026-01-01T10:00:05Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
        packages=(fx.package("com.example.newproc", 10200),),
        sockets=(fx.NEW_SOCK,),
    )
    result = attribute_socket(
        fx.NEW_SOCK,
        uid_packages=None,
        baseline=fx.baseline_with_stable(),
        current=current,
    )
    assert result.attribution_state is AttributionState.PARTIAL
    assert result.package_names == ("com.example.newproc",)


def test_attribute_sockets_is_deterministic() -> None:
    sockets = (
        fx.socket("udp", "0.0.0.0", 53, uid=1000),
        fx.socket("tcp", "0.0.0.0", 4444, uid=10200),
        fx.socket("tcp", "0.0.0.0", 5353, uid=10100),
    )
    first = attribute_sockets(
        sockets,
        uid_packages={10200: ("com.example.newproc",)},
        baseline=fx.baseline_with_stable(),
        current=fx.snapshot(
            fx.ts("2026-01-01T10:00:05Z"),
            processes=(fx.STABLE_A,),
            sockets=sockets,
        ),
    )
    second = attribute_sockets(
        tuple(reversed(sockets)),
        uid_packages={10200: ("com.example.newproc",)},
        baseline=fx.baseline_with_stable(),
        current=fx.snapshot(
            fx.ts("2026-01-01T10:00:05Z"),
            processes=(fx.STABLE_A,),
            sockets=sockets,
        ),
    )
    assert first == second
    # Deterministic order: (protocol, local_address, local_port, uid).
    assert [a.socket.local_port for a in first] == [4444, 5353, 53]


def test_socket_in_baseline_but_not_current_reports_removed() -> None:
    result = attribute_socket(
        fx.STABLE_SOCK,
        baseline=fx.baseline_with_stable(),
        current=fx.snapshot(
            fx.ts("2026-01-01T10:00:05Z"),
            processes=(fx.STABLE_A,),
            sockets=(fx.NEW_SOCK,),
        ),
    )
    assert result.attribution_state is AttributionState.PARTIAL
    assert result.baseline_status == CHANGE_REMOVED