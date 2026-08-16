"""Unit tests for the heuristics evaluation entry point.

No device required. Covers rule coverage/auditability, multi-rule
combination, deterministic ordering, and the empty-report case.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
from android_task_manager.heuristics.evaluate import RULES, evaluate_heuristics
from android_task_manager.heuristics.models import SEVERITY_HIGH, HeuristicReport
from android_task_manager.heuristics.rules import (
    RULE_MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS,
    RULE_NEW_PROCESS_WITH_ACTIVE_SOCKET,
    RULE_NEW_UNCLASSIFIED_PACKAGE_WITH_NEW_PROCESS,
)
from android_task_manager.process.models import ProcessCategory

FIXED_CREATED_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
FIXED_COMPARED_AT = datetime(2026, 8, 15, 12, 30, 0, tzinfo=timezone.utc)
FIXED_EVALUATED_AT = datetime(2026, 8, 15, 13, 0, 0, tzinfo=timezone.utc)


def _proc(name: str, uid: int | None = 10200, category: ProcessCategory = ProcessCategory.USER) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=category)


def _pkg(name: str, uid: int | None = 10200) -> PackageIdentity:
    return PackageIdentity(package_name=name, uid=uid)


def _sock(protocol: str, address: str, port: int, uid: int | None = 10200) -> SocketIdentity:
    return SocketIdentity(protocol=protocol, local_address=address, local_port=port, uid=uid)


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


def _socket_entity(protocol: str, address: str, port: int) -> str:
    return f"{protocol}:{address}:{port}"


_ALL_RULE_IDS = (
    RULE_NEW_PROCESS_WITH_ACTIVE_SOCKET,
    RULE_NEW_UNCLASSIFIED_PACKAGE_WITH_NEW_PROCESS,
    RULE_MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS,
)


def test_evaluate_runs_all_rules_and_reports_rules_applied() -> None:
    report = _report()
    result = evaluate_heuristics(report, _snapshot(), _snapshot(), evaluated_at=FIXED_EVALUATED_AT)
    assert isinstance(result, HeuristicReport)
    assert result.signals == ()
    assert result.rules_applied == _ALL_RULE_IDS
    assert result.evaluated_at == FIXED_EVALUATED_AT


def test_evaluate_combines_signals_from_multiple_rules() -> None:
    """One drift report triggers all three rules at once."""
    report = _report(
        events=(
            # Rule 2: new package + new user process sharing uid 10250.
            _new_event(CATEGORY_PACKAGE, "com.example.newapp"),
            _new_event(CATEGORY_PROCESS, "com.example.newapp"),
            # Rule 1: new process (uid 10200) + new socket (uid 10200).
            _new_event(CATEGORY_PROCESS, "com.example.netprobe"),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 5555)),
            # Rule 3: a second new socket also owned by uid 10200.
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 6666)),
        )
    )
    current = _snapshot(
        processes=frozenset(
            {
                _proc("com.example.newapp", 10250, ProcessCategory.USER),
                _proc("com.example.netprobe", 10200, ProcessCategory.USER),
            }
        ),
        packages=frozenset({_pkg("com.example.newapp", 10250)}),
        sockets=frozenset(
            {
                _sock("tcp", "0.0.0.0", 5555, 10200),
                _sock("tcp", "0.0.0.0", 6666, 10200),
            }
        ),
    )
    result = evaluate_heuristics(report, _snapshot(), current, evaluated_at=FIXED_EVALUATED_AT)
    rule_ids = {signal.rule_id for signal in result.signals}
    assert rule_ids == set(_ALL_RULE_IDS)
    assert len(result.signals) == 3


def test_evaluate_output_is_deterministic() -> None:
    report = _report(
        events=(
            _new_event(CATEGORY_PACKAGE, "com.example.newapp"),
            _new_event(CATEGORY_PROCESS, "com.example.newapp"),
            _new_event(CATEGORY_PROCESS, "com.example.netprobe"),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 5555)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 6666)),
        )
    )
    current = _snapshot(
        processes=frozenset(
            {
                _proc("com.example.newapp", 10250, ProcessCategory.USER),
                _proc("com.example.netprobe", 10200, ProcessCategory.USER),
            }
        ),
        packages=frozenset({_pkg("com.example.newapp", 10250)}),
        sockets=frozenset(
            {
                _sock("tcp", "0.0.0.0", 5555, 10200),
                _sock("tcp", "0.0.0.0", 6666, 10200),
            }
        ),
    )
    first = evaluate_heuristics(report, _snapshot(), current, evaluated_at=FIXED_EVALUATED_AT)
    second = evaluate_heuristics(report, _snapshot(), current, evaluated_at=FIXED_EVALUATED_AT)
    assert first == second
    # HIGH (rule 3, uid 10200) sorts before the two MEDIUM signals, which are
    # ordered by rule_id.
    assert [signal.rule_id for signal in first.signals] == [
        RULE_MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS,
        RULE_NEW_PROCESS_WITH_ACTIVE_SOCKET,
        RULE_NEW_UNCLASSIFIED_PACKAGE_WITH_NEW_PROCESS,
    ]
    assert first.signals[0].severity == SEVERITY_HIGH


def test_evaluate_with_empty_drift_report() -> None:
    result = evaluate_heuristics(_report(), _snapshot(), _snapshot(), evaluated_at=FIXED_EVALUATED_AT)
    assert result.signals == ()
    assert result.rules_applied == _ALL_RULE_IDS


def test_evaluate_signals_are_sorted_by_severity_then_rule_id_then_entity() -> None:
    """Two signals from the same rule: entity decides the tie-break order."""
    report = _report(
        events=(
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 1000)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 1001)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 1002)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 1003)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 1004)),
            _new_event(CATEGORY_SOCKET, _socket_entity("tcp", "0.0.0.0", 1005)),
        )
    )
    current = _snapshot(
        sockets=frozenset(
            {
                _sock("tcp", "0.0.0.0", 1000, 100),
                _sock("tcp", "0.0.0.0", 1001, 100),
                _sock("tcp", "0.0.0.0", 1002, 100),
                _sock("tcp", "0.0.0.0", 1003, 200),
                _sock("tcp", "0.0.0.0", 1004, 200),
                _sock("tcp", "0.0.0.0", 1005, 200),
            }
        )
    )
    result = evaluate_heuristics(report, _snapshot(), current, evaluated_at=FIXED_EVALUATED_AT)
    assert [signal.entity for signal in result.signals] == ["uid=100", "uid=200"]


def test_rules_registry_matches_rule_ids() -> None:
    from android_task_manager.heuristics.rules import RULE_IDS

    assert len(RULES) == 3
    assert tuple(RULE_IDS[rule] for rule in RULES) == _ALL_RULE_IDS