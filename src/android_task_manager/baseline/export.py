"""Session export: JSON serialization and CSV export for baseline drift data.

A pure serialization layer on top of the existing baseline models — it adds
no ADB calls, never touches the Android device, and only writes local files
when explicitly asked to. It does not modify ``snapshot.py``/``diff.py``:
a ``Session`` bundles the snapshots and report those modules already produce.

Serialization rules:

* **Lossless round-trips.** ``snapshot_to_dict`` / ``snapshot_from_dict``
  (and the report/event/session equivalents) preserve every field exactly,
  including ``None``-attributed UIDs, empty sets and unverified flags.
* **Deterministic JSON.** ``frozenset``/``tuple`` fields are emitted as
  arrays sorted into a fixed order (see the ``_sort_key`` helpers, which
  mirror the diff engine's ordering, including ``None`` UIDs sorting before
  any real UID), and ``json.dumps`` uses ``sort_keys=True`` — two exports of
  the same data are byte-identical.
* **Honest ``None``.** Unattributed values serialize as JSON ``null`` and
  deserialize back to ``None`` — never ``0``, never an omitted key.
  CSV has no null concept, so the CSV export renders ``None`` cells as empty
  strings (export-only; CSV is never imported back).
* **Datetime.** ``datetime`` fields use ISO 8601 (``isoformat()``) and are
  restored exactly with ``fromisoformat()``.
* **Enums.** ``ProcessRef.classification`` (a ``ProcessCategory``) is stored
  by its stable value string and restored with ``ProcessCategory(value)``.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..process.models import ProcessCategory
from .models import (
    BaselineSnapshot,
    DriftEvent,
    DriftReport,
    PackageIdentity,
    ProcessRef,
    SocketIdentity,
)


@dataclass(frozen=True)
class Session:
    """A monitoring session: a baseline, a current snapshot, and their drift."""

    baseline: BaselineSnapshot
    current: BaselineSnapshot
    drift_report: DriftReport


# ---------------------------------------------------------------------------
# Deterministic ordering (mirrors the diff engine's identity ordering).
# ---------------------------------------------------------------------------


def _uid_sort_key(uid: int | None) -> int:
    """Sort key for optional UIDs: ``None`` sorts before any real UID."""
    return -1 if uid is None else uid


def _process_sort_key(identity: ProcessRef) -> tuple:
    return (identity.process_name, _uid_sort_key(identity.uid), identity.classification.value)


def _package_sort_key(identity: PackageIdentity) -> tuple:
    return (identity.package_name, _uid_sort_key(identity.uid))


def _socket_sort_key(identity: SocketIdentity) -> tuple:
    return (
        identity.protocol,
        identity.local_address,
        identity.local_port,
        _uid_sort_key(identity.uid),
    )


def _event_sort_key(event: DriftEvent) -> tuple:
    return (event.category, event.change_type, event.entity)


# ---------------------------------------------------------------------------
# BaselineSnapshot
# ---------------------------------------------------------------------------


def snapshot_to_dict(snapshot: BaselineSnapshot) -> dict[str, Any]:
    """Serialize a snapshot to a JSON-ready dict (deterministic order)."""
    return {
        "created_at": snapshot.created_at.isoformat(),
        "device_serial": snapshot.device_serial,
        "processes": [
            {
                "uid": identity.uid,
                "process_name": identity.process_name,
                "classification": identity.classification.value,
            }
            for identity in sorted(snapshot.processes, key=_process_sort_key)
        ],
        "packages": [
            {"package_name": identity.package_name, "uid": identity.uid}
            for identity in sorted(snapshot.packages, key=_package_sort_key)
        ],
        "sockets": [
            {
                "protocol": identity.protocol,
                "local_address": identity.local_address,
                "local_port": identity.local_port,
                "uid": identity.uid,
            }
            for identity in sorted(snapshot.sockets, key=_socket_sort_key)
        ],
        "processes_verified": snapshot.processes_verified,
        "packages_verified": snapshot.packages_verified,
        "sockets_verified": snapshot.sockets_verified,
    }


def snapshot_from_dict(data: dict[str, Any]) -> BaselineSnapshot:
    """Reconstruct a snapshot from :func:`snapshot_to_dict` output."""
    return BaselineSnapshot(
        created_at=datetime.fromisoformat(data["created_at"]),
        device_serial=data["device_serial"],
        processes=frozenset(
            ProcessRef(
                uid=entry["uid"],
                process_name=entry["process_name"],
                classification=ProcessCategory(entry["classification"]),
            )
            for entry in data["processes"]
        ),
        packages=frozenset(
            PackageIdentity(package_name=entry["package_name"], uid=entry["uid"])
            for entry in data["packages"]
        ),
        sockets=frozenset(
            SocketIdentity(
                protocol=entry["protocol"],
                local_address=entry["local_address"],
                local_port=entry["local_port"],
                uid=entry["uid"],
            )
            for entry in data["sockets"]
        ),
        processes_verified=data["processes_verified"],
        packages_verified=data["packages_verified"],
        sockets_verified=data["sockets_verified"],
    )


# ---------------------------------------------------------------------------
# DriftEvent / DriftReport
# ---------------------------------------------------------------------------


def drift_event_to_dict(event: DriftEvent) -> dict[str, Any]:
    """Serialize a drift event to a JSON-ready dict."""
    return {
        "category": event.category,
        "change_type": event.change_type,
        "severity": event.severity,
        "entity": event.entity,
        "baseline_value": event.baseline_value,
        "current_value": event.current_value,
        "explanation": event.explanation,
    }


def drift_event_from_dict(data: dict[str, Any]) -> DriftEvent:
    """Reconstruct a drift event from :func:`drift_event_to_dict` output."""
    return DriftEvent(
        category=data["category"],
        change_type=data["change_type"],
        severity=data["severity"],
        entity=data["entity"],
        baseline_value=data["baseline_value"],
        current_value=data["current_value"],
        explanation=data["explanation"],
    )


def drift_report_to_dict(report: DriftReport) -> dict[str, Any]:
    """Serialize a drift report to a JSON-ready dict (events sorted)."""
    return {
        "baseline_created_at": report.baseline_created_at.isoformat(),
        "compared_at": report.compared_at.isoformat(),
        "events": [
            drift_event_to_dict(event)
            for event in sorted(report.events, key=_event_sort_key)
        ],
        "unverified_categories": list(report.unverified_categories),
    }


def drift_report_from_dict(data: dict[str, Any]) -> DriftReport:
    """Reconstruct a drift report from :func:`drift_report_to_dict` output."""
    return DriftReport(
        baseline_created_at=datetime.fromisoformat(data["baseline_created_at"]),
        compared_at=datetime.fromisoformat(data["compared_at"]),
        events=tuple(drift_event_from_dict(entry) for entry in data["events"]),
        unverified_categories=tuple(data["unverified_categories"]),
    )


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


def session_to_dict(session: Session) -> dict[str, Any]:
    """Serialize a session (baseline + current + drift report) to a dict."""
    return {
        "baseline": snapshot_to_dict(session.baseline),
        "current": snapshot_to_dict(session.current),
        "drift_report": drift_report_to_dict(session.drift_report),
    }


def session_from_dict(data: dict[str, Any]) -> Session:
    """Reconstruct a session from :func:`session_to_dict` output."""
    return Session(
        baseline=snapshot_from_dict(data["baseline"]),
        current=snapshot_from_dict(data["current"]),
        drift_report=drift_report_from_dict(data["drift_report"]),
    )


def to_json(obj: Session) -> str:
    """Serialize a session to a stable, human-readable JSON string."""
    return json.dumps(session_to_dict(obj), indent=2, sort_keys=True, ensure_ascii=False)


def from_json(json_str: str) -> Session:
    """Deserialize a session from :func:`to_json` output."""
    return session_from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# CSV export (events only — export-only, no CSV import).
# ---------------------------------------------------------------------------

_CSV_COLUMNS = (
    "category",
    "change_type",
    "severity",
    "entity",
    "baseline_value",
    "current_value",
    "explanation",
)


def drift_events_to_csv(report: DriftReport) -> str:
    """Render the report's events as CSV text: header row plus one row per event.

    Events are emitted in the deterministic (category, change_type, entity)
    order. ``None`` values become empty cells — CSV has no null concept, and
    this is export-only. An empty report yields just the header row.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(list(_CSV_COLUMNS))
    for event in sorted(report.events, key=_event_sort_key):
        writer.writerow(
            [
                event.category,
                event.change_type,
                event.severity,
                event.entity,
                "" if event.baseline_value is None else event.baseline_value,
                "" if event.current_value is None else event.current_value,
                event.explanation,
            ]
        )
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Explicit file-writing helpers (no directory creation, no default paths).
# ---------------------------------------------------------------------------


def write_session_json(session: Session, path: str | Path) -> None:
    """Write a session's JSON export to *path*.

    The parent directory is not created: a missing parent raises naturally
    (``FileNotFoundError``) — path management is a CLI/UX concern for a
    later task.
    """
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(to_json(session))


def write_drift_events_csv(report: DriftReport, path: str | Path) -> None:
    """Write a report's events CSV export to *path*.

    Same no-directory-creation policy as :func:`write_session_json`.
    """
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(drift_events_to_csv(report))