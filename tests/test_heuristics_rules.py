"""Unit tests for the heuristic rules (one per rule: positive, negative,
unverified-category, and None-uid cases).

No device required: rules consume in-memory ``DriftReport`` +
``BaselineSnapshot`` fixtures. Reasons must be instance-specific — tests
assert the actual entity name appears in them.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from android_task_manager.baseline.models import (
    CATEGORY_PACKAGE,
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
    CHANGE_NEW,
    BaselineSnapshot,
    DriftEvent,
    DriftReport,
    PackageIdentity,
    ProcessRef,
    SocketIdentity,
)
from android_task_manager.heuristics.models import SEVERITY_HIGH, SEVERITY_MEDIUM
from android_task_manager.heuristics.rules import (
    RULE_MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS,
    RULE_NEW_PROCESS_WITH_ACTIVE_SOCKET,
    RULE_NEW_UNCLASSIFIED_PACKAGE_WITH_NEW_PROCESS,
    rule_multiple_new_listening_sockets_same_process,
    rule_new_process_with_active_socket,
    rule_new_unclassified_package_with_new_process,
)
from android_task_manager.process.models import ProcessCategory

FIXED_CREATED_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
FIXED_COMPARED_AT = datetime(2026, 8, 15, 12, 30, 0, tzinfo=timezone.utc)


def _proc(name: str, uid: int | None = 10200, category: ProcessCategory = ProcessCategory.USER) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=category)


def _pkg(name: str, uid: int | None = 10200) -> PackageIdentity:
    return PackageIdentity(package_name=name, uid=uid)


def _sock(protocol: str, address: str, port: int, uid: int | None = 10200) -> SocketIdentity:
    return SocketIdentity(protocol=protocol, local_address=address, local_port=port, uid=uid)


def _socket_entity(protocol: str, address: str, port: int) -> str:
    return f"{protocol}:{address}:{port}"


def _snapshot(
    *,
    processes: frozenset[ProcessRef] = frozenset(),
    packages: frozenset[PackageIdentity] = frozenset(),
    sockets: frozenset[SocketIdentity] = frozenset(),
) -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=FIXED_CREATED_AT,
        device_serial="R58M1234567",
        processes=processes,
        packages=packages,
        sockets=sockets,
    )


def _report(
    *,
    events: tuple[DriftEvent, ...] = (),
    unverified: tuple[str, ...] = (),
) -> DriftReport:
    return DriftReport(
        baseline_created_at=FIXED_CREATED_AT,
        compared_at=FIXED_COMPARED_AT,
        events=events,
        unverified_categories=unverified,
    )


def _new_event(category: str, entity: str) -> DriftEvent:
    return DriftEvent(category=category, change_type=CHANGE_NEW, entity=entity)


def _empty_baseline() -> BaselineSnapshot:
    return _snapshot()


# ---------------------------------------------------------------------------
# Rule 1: new process with new socket owned by the same UID.
# ---------------------------------------------------------------------------


def test_rule1_fires_when_new_process_has_new_socket_with_matching_uid() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PROCESS, "com.example.app"),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
        )
    )
    current = _snapshot(
        processes=frozenset({_proc("com.example.app", 10200)}),
        sockets=frozenset({_sock("tcp", "0.0.0.0", 4444, 10200)}),
    )
    signals = rule_new_process_with_active_socket(report, _empty_baseline(), current)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.rule_id == RULE_NEW_PROCESS_WITH_ACTIVE_SOCKET
    assert signal.severity == SEVERITY_MEDIUM
    assert signal.entity == "com.example.app"
    assert "com.example.app" in signal.reason
    assert signal.contributing_events == ("com.example.app", "tcp:0.0.0.0:4444")


def test_rule1_single_signal_for_process_with_multiple_matching_sockets() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PROCESS, "com.example.app"),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
            _new_event(CATEGORY_SOCKET, _socket_entity("udp", "0.0.0.0", 53)),
        )
    )
    current = _snapshot(
        processes=frozenset({_proc("com.example.app", 10200)}),
        sockets=frozenset(
            {
                _sock("tcp", "0.0.0.0", 4444, 10200),
                _sock("udp", "0.0.0.0", 53, 10200),
            }
        ),
    )
    signals = rule_new_process_with_active_socket(report, _empty_baseline(), current)
    assert len(signals) == 1
    assert "2 new network sockets" in signals[0].reason
    assert set(signals[0].contributing_events) == {
        "com.example.app",
        "tcp:0.0.0.0:4444",
        "udp:0.0.0.0:53",
    }


def test_rule1_not_fire_when_new_process_has_no_new_socket() -> None:
    report = _report(events=(_new_event(CATEGORY_PROCESS, "com.example.app"),))
    current = _snapshot(processes=frozenset({_proc("com.example.app", 10200)}))
    assert rule_new_process_with_active_socket(report, _empty_baseline(), current) == []


def test_rule1_not_fire_when_new_socket_uid_differs() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PROCESS, "com.example.app"),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
        )
    )
    current = _snapshot(
        processes=frozenset({_proc("com.example.app", 10200)}),
        sockets=frozenset({_sock("tcp", "0.0.0.0", 4444, 10299)}),
    )
    assert rule_new_process_with_active_socket(report, _empty_baseline(), current) == []


def test_rule1_not_fire_when_socket_uid_is_none() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PROCESS, "com.example.app"),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
        )
    )
    current = _snapshot(
        processes=frozenset({_proc("com.example.app", 10200)}),
        sockets=frozenset({_sock("tcp", "0.0.0.0", 4444, None)}),
    )
    assert rule_new_process_with_active_socket(report, _empty_baseline(), current) == []


def test_rule1_not_fire_when_process_uid_is_none() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PROCESS, "uidless.app"),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
        )
    )
    current = _snapshot(
        processes=frozenset({_proc("uidless.app", None)}),
        sockets=frozenset({_sock("tcp", "0.0.0.0", 4444, 10200)}),
    )
    assert rule_new_process_with_active_socket(report, _empty_baseline(), current) == []


def test_rule1_not_fire_when_identity_missing_from_current_snapshot() -> None:
    """Defensive: an event whose identity cannot be resolved never fires."""
    report = _report(
        events=(
            _new_event(CATEGORY_PROCESS, "com.example.app"),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
        )
    )
    assert rule_new_process_with_active_socket(report, _empty_baseline(), _snapshot()) == []


@pytest.mark.parametrize(
    "unverified",
    [
        (CATEGORY_PROCESS,),
        (CATEGORY_SOCKET,),
        (CATEGORY_PROCESS, CATEGORY_SOCKET),
    ],
)
def test_rule1_unverified_category_skipped_even_with_matching_events(unverified) -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PROCESS, "com.example.app"),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
        ),
        unverified=unverified,
    )
    current = _snapshot(
        processes=frozenset({_proc("com.example.app", 10200)}),
        sockets=frozenset({_sock("tcp", "0.0.0.0", 4444, 10200)}),
    )
    assert rule_new_process_with_active_socket(report, _empty_baseline(), current) == []


# ---------------------------------------------------------------------------
# Rule 2: new package with a new user-classified process.
# ---------------------------------------------------------------------------


def test_rule2_fires_when_new_package_has_new_user_process_with_matching_uid() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PACKAGE, "com.example.newapp"),
            _new_event(CATEGORY_PROCESS, "com.example.newapp"),
        )
    )
    current = _snapshot(
        packages=frozenset({_pkg("com.example.newapp", 10250)}),
        processes=frozenset({_proc("com.example.newapp", 10250, ProcessCategory.USER)}),
    )
    signals = rule_new_unclassified_package_with_new_process(report, _empty_baseline(), current)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.rule_id == RULE_NEW_UNCLASSIFIED_PACKAGE_WITH_NEW_PROCESS
    assert signal.severity == SEVERITY_MEDIUM
    assert signal.entity == "com.example.newapp"
    assert "com.example.newapp" in signal.reason
    assert signal.contributing_events == ("com.example.newapp", "com.example.newapp")


def test_rule2_fires_for_secondary_process_with_same_uid() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PACKAGE, "com.example.newapp"),
            _new_event(CATEGORY_PROCESS, "com.example.newapp:remote"),
        )
    )
    current = _snapshot(
        packages=frozenset({_pkg("com.example.newapp", 10250)}),
        processes=frozenset({_proc("com.example.newapp:remote", 10250, ProcessCategory.USER)}),
    )
    signals = rule_new_unclassified_package_with_new_process(report, _empty_baseline(), current)
    assert len(signals) == 1
    assert signals[0].entity == "com.example.newapp"


def test_rule2_not_fire_when_new_process_uid_differs() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PACKAGE, "com.example.newapp"),
            _new_event(CATEGORY_PROCESS, "com.example.newapp"),
        )
    )
    current = _snapshot(
        packages=frozenset({_pkg("com.example.newapp", 10250)}),
        processes=frozenset({_proc("com.example.newapp", 10300, ProcessCategory.USER)}),
    )
    assert rule_new_unclassified_package_with_new_process(report, _empty_baseline(), current) == []


def test_rule2_not_fire_when_process_is_not_user_classified() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PACKAGE, "com.example.newapp"),
            _new_event(CATEGORY_PROCESS, "com.example.newapp"),
        )
    )
    current = _snapshot(
        packages=frozenset({_pkg("com.example.newapp", 10250)}),
        processes=frozenset({_proc("com.example.newapp", 10250, ProcessCategory.SYSTEM)}),
    )
    assert rule_new_unclassified_package_with_new_process(report, _empty_baseline(), current) == []


def test_rule2_not_fire_when_package_uid_is_none() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PACKAGE, "com.example.newapp"),
            _new_event(CATEGORY_PROCESS, "com.example.newapp"),
        )
    )
    current = _snapshot(
        packages=frozenset({_pkg("com.example.newapp", None)}),
        processes=frozenset({_proc("com.example.newapp", 10250, ProcessCategory.USER)}),
    )
    assert rule_new_unclassified_package_with_new_process(report, _empty_baseline(), current) == []


def test_rule2_not_fire_when_process_uid_is_none() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PACKAGE, "com.example.newapp"),
            _new_event(CATEGORY_PROCESS, "com.example.newapp"),
        )
    )
    current = _snapshot(
        packages=frozenset({_pkg("com.example.newapp", 10250)}),
        processes=frozenset({_proc("com.example.newapp", None, ProcessCategory.USER)}),
    )
    assert rule_new_unclassified_package_with_new_process(report, _empty_baseline(), current) == []


def test_rule2_not_fire_when_only_package_or_only_process_is_new() -> None:
    package_only = _report(events=(_new_event(CATEGORY_PACKAGE, "com.example.newapp"),))
    current = _snapshot(
        packages=frozenset({_pkg("com.example.newapp", 10250)}),
        processes=frozenset({_proc("com.example.newapp", 10250, ProcessCategory.USER)}),
    )
    assert rule_new_unclassified_package_with_new_process(report=package_only, baseline=_empty_baseline(), current=current) == []
    process_only = _report(events=(_new_event(CATEGORY_PROCESS, "com.example.newapp"),))
    assert rule_new_unclassified_package_with_new_process(report=process_only, baseline=_empty_baseline(), current=current) == []


@pytest.mark.parametrize("unverified", [(CATEGORY_PACKAGE,), (CATEGORY_PROCESS,)])
def test_rule2_unverified_category_skipped_even_with_matching_events(unverified) -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PACKAGE, "com.example.newapp"),
            _new_event(CATEGORY_PROCESS, "com.example.newapp"),
        ),
        unverified=unverified,
    )
    current = _snapshot(
        packages=frozenset({_pkg("com.example.newapp", 10250)}),
        processes=frozenset({_proc("com.example.newapp", 10250, ProcessCategory.USER)}),
    )
    assert rule_new_unclassified_package_with_new_process(report, _empty_baseline(), current) == []


# ---------------------------------------------------------------------------
# Rule 3: multiple new listening sockets opened by one UID.
# ---------------------------------------------------------------------------


def test_rule3_fires_when_two_new_sockets_share_a_uid() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 5555)),
        )
    )
    current = _snapshot(
        sockets=frozenset(
            {
                _sock("tcp", "0.0.0.0", 4444, 10200),
                _sock("tcp", "0.0.0.0", 5555, 10200),
            }
        )
    )
    signals = rule_multiple_new_listening_sockets_same_process(report, _empty_baseline(), current)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.rule_id == RULE_MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS
    assert signal.severity == SEVERITY_HIGH
    assert signal.entity == "uid=10200"
    assert "10200" in signal.reason
    assert "2" in signal.reason
    assert signal.contributing_events == ("tcp:0.0.0.0:4444", "tcp:0.0.0.0:5555")


def test_rule3_fires_once_per_uid_with_count_in_reason() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 5555)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 6666)),
            _new_event(CATEGORY_SOCKET, _socket_entity("udp", "0.0.0.0", 53)),
        )
    )
    current = _snapshot(
        sockets=frozenset(
            {
                _sock("tcp", "0.0.0.0", 4444, 10200),
                _sock("tcp", "0.0.0.0", 5555, 10200),
                _sock("tcp", "0.0.0.0", 6666, 10200),
                _sock("udp", "0.0.0.0", 53, 10240),
            }
        )
    )
    signals = rule_multiple_new_listening_sockets_same_process(report, _empty_baseline(), current)
    assert len(signals) == 1
    by_uid = {signal.entity: signal for signal in signals}
    assert "uid=10200" in by_uid
    assert "uid=10240" not in by_uid  # single socket: no signal
    assert "3" in by_uid["uid=10200"].reason
    assert by_uid["uid=10200"].contributing_events == (
        "tcp:0.0.0.0:4444",
        "tcp:0.0.0.0:5555",
        "tcp:0.0.0.0:6666",
    )


def test_rule3_not_fire_with_single_new_socket() -> None:
    report = _report(events=(_new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),))
    current = _snapshot(sockets=frozenset({_sock("tcp", "0.0.0.0", 4444, 10200)}))
    assert rule_multiple_new_listening_sockets_same_process(report, _empty_baseline(), current) == []


def test_rule3_not_fire_when_two_sockets_have_different_uids() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 5555)),
        )
    )
    current = _snapshot(
        sockets=frozenset(
            {
                _sock("tcp", "0.0.0.0", 4444, 10200),
                _sock("tcp", "0.0.0.0", 5555, 10240),
            }
        )
    )
    assert rule_multiple_new_listening_sockets_same_process(report, _empty_baseline(), current) == []


def test_rule3_not_fire_when_sockets_have_unknown_uids() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 5555)),
        )
    )
    current = _snapshot(
        sockets=frozenset(
            {
                _sock("tcp", "0.0.0.0", 4444, None),
                _sock("tcp", "0.0.0.0", 5555, None),
            }
        )
    )
    assert rule_multiple_new_listening_sockets_same_process(report, _empty_baseline(), current) == []


def test_rule3_not_fire_when_identity_missing_from_current_snapshot() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 5555)),
        )
    )
    assert rule_multiple_new_listening_sockets_same_process(report, _empty_baseline(), _snapshot()) == []


def test_rule3_unverified_socket_category_skipped_even_with_matching_events() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 4444)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 5555)),
        ),
        unverified=(CATEGORY_SOCKET,),
    )
    current = _snapshot(
        sockets=frozenset(
            {
                _sock("tcp", "0.0.0.0", 4444, 10200),
                _sock("tcp", "0.0.0.0", 5555, 10200),
            }
        )
    )
    assert rule_multiple_new_listening_sockets_same_process(report, _empty_baseline(), current) == []