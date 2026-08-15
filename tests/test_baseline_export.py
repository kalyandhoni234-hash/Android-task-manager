"""Unit tests for baseline session export: JSON round-trips and CSV output.

No device required: everything is pure serialization of in-memory
dataclasses. Round-trips are exact equality checks — including ``None``
UIDs, unverified categories, empty sets and timezone-aware datetimes.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

import pytest

from android_task_manager.baseline.export import (
    Session,
    drift_event_from_dict,
    drift_event_to_dict,
    drift_events_to_csv,
    drift_report_from_dict,
    drift_report_to_dict,
    from_json,
    session_from_dict,
    session_to_dict,
    snapshot_from_dict,
    snapshot_to_dict,
    to_json,
    write_drift_events_csv,
    write_session_json,
)
from android_task_manager.baseline.models import (
    SEVERITY_INFO,
    BaselineSnapshot,
    DriftEvent,
    DriftReport,
    PackageIdentity,
    ProcessRef,
    SocketIdentity,
)
from android_task_manager.process.models import ProcessCategory

FIXED_CREATED_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
FIXED_COMPARED_AT = datetime(2026, 8, 15, 12, 30, 0, tzinfo=timezone.utc)
SERIAL = "R58M1234567"


def _proc(name: str, uid: int | None = 10200, category: ProcessCategory = ProcessCategory.USER) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=category)


def _pkg(name: str, uid: int | None = 10200) -> PackageIdentity:
    return PackageIdentity(package_name=name, uid=uid)


def _sock(protocol: str = "tcp", address: str = "0.0.0.0", port: int = 4444, uid: int | None = 10200) -> SocketIdentity:
    return SocketIdentity(protocol=protocol, local_address=address, local_port=port, uid=uid)


def _snapshot(
    *,
    processes: frozenset[ProcessRef] | None = None,
    packages: frozenset[PackageIdentity] | None = None,
    sockets: frozenset[SocketIdentity] | None = None,
    processes_verified: bool = True,
    packages_verified: bool = True,
    sockets_verified: bool = True,
) -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=FIXED_CREATED_AT,
        device_serial=SERIAL,
        processes=processes if processes is not None else frozenset(),
        packages=packages if packages is not None else frozenset(),
        sockets=sockets if sockets is not None else frozenset(),
        processes_verified=processes_verified,
        packages_verified=packages_verified,
        sockets_verified=sockets_verified,
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


def _full_snapshot() -> BaselineSnapshot:
    """A snapshot with every field populated, including a ``uid=None`` entry."""
    return _snapshot(
        processes=frozenset(
            {
                _proc("com.example.app", 10200),
                _proc("[kworker/0:1]", 0, ProcessCategory.KERNEL_THREAD),
                _proc("system_app", 1000, ProcessCategory.SYSTEM),
                _proc("uidless.app", None),
            }
        ),
        packages=frozenset({_pkg("com.example.app", 10200), _pkg("uidless.pkg", None)}),
        sockets=frozenset({_sock("tcp", "0.0.0.0", 4444, 10200), _sock("udp", "0.0.0.0", 53, None)}),
    )


def _full_session() -> Session:
    return Session(
        baseline=_full_snapshot(),
        current=_snapshot(
            processes=frozenset({_proc("com.example.app", 10200), _proc("com.example.new", 10250)}),
            packages=frozenset({_pkg("com.example.app", 10200)}),
            sockets=frozenset({_sock("tcp", "0.0.0.0", 4444), _sock("tcp6", "::", 5050, 1000)}),
        ),
        drift_report=_report(
            events=(
                # Canonical (category, change_type, entity) order — matching
                # the deterministic order the diff engine and exporter emit.
                DriftEvent(
                    category="package",
                    change_type="REMOVED",
                    entity="uidless.pkg",
                    baseline_value="uidless.pkg (uid unknown)",
                    explanation="Package no longer installed",
                ),
                DriftEvent(
                    category="process",
                    change_type="NEW",
                    entity="com.example.new",
                    current_value="com.example.new (uid 10250, user)",
                    explanation="New process observed",
                ),
                DriftEvent(
                    category="socket",
                    change_type="NEW",
                    entity="tcp6::::5050",
                    current_value="tcp6::::5050 (uid 1000)",
                    explanation="New listening socket detected",
                ),
            ),
            unverified=("socket",),
        ),
    )


# ---------------------------------------------------------------------------
# JSON round-trips.
# ---------------------------------------------------------------------------


def test_snapshot_json_round_trip() -> None:
    snapshot = _full_snapshot()
    via_dict = snapshot_from_dict(snapshot_to_dict(snapshot))
    assert via_dict == snapshot
    via_json = snapshot_from_dict(json.loads(json.dumps(snapshot_to_dict(snapshot))))
    assert via_json == snapshot


def test_snapshot_round_trip_with_unverified_category() -> None:
    snapshot = _snapshot(sockets_verified=False)
    restored = snapshot_from_dict(snapshot_to_dict(snapshot))
    assert restored == snapshot
    assert restored.sockets_verified is False
    assert restored.processes_verified is True
    assert restored.packages_verified is True


def test_drift_report_json_round_trip() -> None:
    report = _full_session().drift_report
    restored = drift_report_from_dict(drift_report_to_dict(report))
    assert restored == report
    assert len(restored.events) == 3
    assert restored.unverified_categories == ("socket",)
    assert isinstance(restored.events, tuple)


def test_drift_report_round_trip_empty_events() -> None:
    report = _report(unverified=("process",))
    restored = drift_report_from_dict(drift_report_to_dict(report))
    assert restored == report
    assert restored.events == ()
    assert restored.events == tuple()
    assert restored.unverified_categories == ("process",)


def test_session_json_round_trip() -> None:
    session = _full_session()
    assert from_json(to_json(session)) == session


def test_json_output_is_deterministic() -> None:
    session = _full_session()
    assert to_json(session) == to_json(session)
    shuffle_order = session_from_dict(session_to_dict(session))
    assert to_json(shuffle_order) == to_json(session)


def test_frozenset_order_does_not_affect_output() -> None:
    first = _snapshot(
        processes=frozenset({_proc("b.app"), _proc("a.app"), _proc("c.app")})
    )
    reversed_input = _snapshot(
        processes=frozenset({_proc("c.app"), _proc("b.app"), _proc("a.app")})
    )
    assert to_json(Session(first, first, _report())) == to_json(Session(reversed_input, reversed_input, _report()))


def test_classification_values_round_trip_for_all_categories() -> None:
    snapshot = _snapshot(
        processes=frozenset(
            {
                _proc("a.kernel", 0, ProcessCategory.KERNEL_THREAD),
                _proc("a.system", 1000, ProcessCategory.SYSTEM),
                _proc("a.user", 10200, ProcessCategory.USER),
            }
        )
    )
    restored = snapshot_from_dict(snapshot_to_dict(snapshot))
    assert restored == snapshot
    classifications = {identity.classification for identity in restored.processes}
    assert classifications == {
        ProcessCategory.KERNEL_THREAD,
        ProcessCategory.SYSTEM,
        ProcessCategory.USER,
    }


def test_empty_snapshot_round_trip() -> None:
    snapshot = _snapshot()
    assert snapshot_from_dict(snapshot_to_dict(snapshot)) == snapshot


# ---------------------------------------------------------------------------
# None handling.
# ---------------------------------------------------------------------------


def test_none_uid_serializes_as_null_not_zero() -> None:
    session = Session(
        baseline=_snapshot(
            processes=frozenset({_proc("uidless.app", None)}),
            packages=frozenset({_pkg("uidless.pkg", None)}),
            sockets=frozenset({_sock("udp", "0.0.0.0", 53, None)}),
        ),
        current=_snapshot(),
        drift_report=_report(),
    )
    text = to_json(session)
    assert '"uid": null' in text
    data = json.loads(text)["baseline"]
    assert data["processes"][0]["uid"] is None
    assert data["packages"][0]["uid"] is None
    assert data["sockets"][0]["uid"] is None
    restored = from_json(text)
    assert restored.baseline.processes == frozenset({_proc("uidless.app", None)})
    assert restored.baseline.packages == frozenset({_pkg("uidless.pkg", None)})
    assert restored.baseline.sockets == frozenset({_sock("udp", "0.0.0.0", 53, None)})


def test_event_none_values_round_trip() -> None:
    event = DriftEvent(category="socket", change_type="REMOVED", entity="tcp:0.0.0.0:1")
    restored = drift_event_from_dict(drift_event_to_dict(event))
    assert restored == event
    assert restored.baseline_value is None
    assert restored.current_value is None


# ---------------------------------------------------------------------------
# CSV export.
# ---------------------------------------------------------------------------


def test_drift_events_to_csv_header_and_rows() -> None:
    report = _report(
        events=(
            DriftEvent(
                category="package",
                change_type="REMOVED",
                entity="com.example.uninstalled",
                baseline_value="com.example.uninstalled (uid unknown)",
                explanation="Package no longer installed",
            ),
            DriftEvent(
                category="process",
                change_type="NEW",
                entity="com.example.newproc",
                current_value="com.example.newproc (uid 10250, user)",
                explanation="New process observed",
            ),
            DriftEvent(
                category="socket",
                change_type="NEW",
                entity="tcp:0.0.0.0:9999",
                current_value="tcp:0.0.0.0:9999 (uid 10211)",
                explanation="New listening socket detected",
            ),
        )
    )
    rows = list(csv.reader(io.StringIO(drift_events_to_csv(report))))
    assert rows[0] == [
        "category",
        "change_type",
        "severity",
        "entity",
        "baseline_value",
        "current_value",
        "explanation",
    ]
    # Events are deterministic (category, change_type, entity) order.
    assert [row[0:4] for row in rows[1:]] == [
        ["package", "REMOVED", SEVERITY_INFO, "com.example.uninstalled"],
        ["process", "NEW", SEVERITY_INFO, "com.example.newproc"],
        ["socket", "NEW", SEVERITY_INFO, "tcp:0.0.0.0:9999"],
    ]
    assert rows[1][4:] == ["com.example.uninstalled (uid unknown)", "", "Package no longer installed"]
    assert rows[2][4:] == ["", "com.example.newproc (uid 10250, user)", "New process observed"]


def test_drift_events_to_csv_empty_report() -> None:
    rows = list(csv.reader(io.StringIO(drift_events_to_csv(_report()))))
    assert rows == [["category", "change_type", "severity", "entity", "baseline_value", "current_value", "explanation"]]


def test_drift_events_to_csv_escapes_embedded_separators() -> None:
    report = _report(
        events=(
            DriftEvent(
                category="process",
                change_type="NEW",
                entity="com.example,app",
                current_value="com.example,app (uid 10200, user)",
                explanation="New process observed",
            ),
        )
    )
    rows = list(csv.reader(io.StringIO(drift_events_to_csv(report))))
    assert len(rows) == 2
    assert rows[1][3] == "com.example,app"
    assert rows[1][5] == "com.example,app (uid 10200, user)"
    assert rows[1][4] == ""  # NEW event: no baseline value


# ---------------------------------------------------------------------------
# File-writing helpers (tmp_path).
# ---------------------------------------------------------------------------


def test_write_session_json_writes_file(tmp_path) -> None:
    path = tmp_path / "session.json"
    session = _full_session()
    write_session_json(session, path)
    assert path.read_text(encoding="utf-8") == to_json(session)
    loaded = from_json(path.read_text(encoding="utf-8"))
    assert loaded == session


def test_write_drift_events_csv_writes_file(tmp_path) -> None:
    path = tmp_path / "drift.csv"
    report = _report(events=_full_session().drift_report.events)
    write_drift_events_csv(report, path)
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    assert rows[0][0] == "category"
    assert len(rows) == 4  # header + 3 events


def test_write_helpers_do_not_create_missing_directories(tmp_path) -> None:
    missing = tmp_path / "no" / "such" / "dir" / "session.json"
    with pytest.raises(FileNotFoundError):
        write_session_json(_full_session(), missing)
    with pytest.raises(FileNotFoundError):
        write_drift_events_csv(_report(), missing)