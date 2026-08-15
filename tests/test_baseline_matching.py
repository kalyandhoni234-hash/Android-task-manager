"""Unit tests for the drift-driven identity projections (baseline/matching).

These helpers feed the GUI highlight layers ("NEW" badges); they reuse the
same frozenset difference the diff engine applies and must refuse to
project unverified categories.
"""

from __future__ import annotations

from datetime import datetime, timezone

from android_task_manager.baseline import (
    new_process_refs,
    new_socket_identities,
)
from android_task_manager.baseline.diff import diff_snapshot
from android_task_manager.baseline.models import (
    BaselineSnapshot,
    DriftReport,
    ProcessRef,
    SocketIdentity,
)
from android_task_manager.process.models import ProcessCategory

_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


def _snapshot(
    processes=(),
    sockets=(),
    *,
    processes_verified=True,
    sockets_verified=True,
) -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=_AT,
        device_serial="TEST123",
        processes=frozenset(processes),
        sockets=frozenset(sockets),
        processes_verified=processes_verified,
        sockets_verified=sockets_verified,
    )


def _proc(name: str, uid: int | None) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=ProcessCategory.USER)


def _sock(addr: str, port: int, uid: int | None = None) -> SocketIdentity:
    return SocketIdentity(
        protocol="tcp",
        local_address=addr,
        local_port=port,
        uid=uid,
    )


class TestNewProcessRefs:
    def test_returns_only_new_identities(self):
        baseline = _snapshot(processes=(_proc("com.kept.app", 10002),))
        current = _snapshot(
            processes=(
                _proc("com.kept.app", 10002),
                _proc("com.new.app", 10003),
            )
        )
        report = diff_snapshot(baseline, current)
        assert new_process_refs(report, baseline, current) == frozenset(
            {_proc("com.new.app", 10003)}
        )

    def test_empty_when_nothing_is_new(self):
        base = _snapshot(processes=(_proc("a", 1),))
        report = diff_snapshot(base, base)
        assert new_process_refs(report, base, base) == frozenset()

    def test_unverified_category_returns_empty_never_fabricated(self):
        """A category the diff engine could not verify must not
        highlight anything — the projection would otherwise invent
        NEW rows from unverified data."""
        baseline = _snapshot(processes=(_proc("com.kept.app", 10002),), processes_verified=False)
        current = _snapshot(
            processes=(
                _proc("com.kept.app", 10002),
                _proc("com.new.app", 10003),
            ),
            processes_verified=True,
        )
        report = diff_snapshot(baseline, current)
        assert "process" in report.unverified_categories
        assert new_process_refs(report, baseline, current) == frozenset()


class TestNewSocketIdentities:
    def test_returns_only_new_sockets(self):
        baseline = _snapshot(sockets=(_sock("10.0.0.1", 53),))
        current = _snapshot(
            sockets=(
                _sock("10.0.0.1", 53),
                _sock("0.0.0.0", 4444),
            )
        )
        report = diff_snapshot(baseline, current)
        assert new_socket_identities(report, baseline, current) == frozenset(
            {_sock("0.0.0.0", 4444)}
        )

    def test_unverified_socket_category_returns_empty(self):
        baseline = _snapshot(sockets=(), sockets_verified=False)
        current = _snapshot(sockets=(_sock("0.0.0.0", 4444),), sockets_verified=True)
        report = diff_snapshot(baseline, current)
        assert "socket" in report.unverified_categories
        assert new_socket_identities(report, baseline, current) == frozenset()

    def test_ignores_categories_reported_unverified_by_the_report_itself(self):
        """The guard reads the report's own unverified list, so a report
        built with an unverified socket category yields no sockets even
        when both sides *say* verified."""
        report = DriftReport(
            baseline_created_at=_AT,
            compared_at=_AT,
            unverified_categories=("socket",),
        )
        baseline = _snapshot(sockets=())
        current = _snapshot(sockets=(_sock("0.0.0.0", 4444),))
        assert new_socket_identities(report, baseline, current) == frozenset()