"""Baseline drift detection.

Captures identity-only snapshots of device state (processes, packages,
listening sockets) and diffs them to report structural *facts* — what is
new and what is gone. The diff engine assigns no risk: every event has
``INFO`` severity, with heuristics/alerting explicitly deferred.

Current scope (Phase 1/3): in-memory snapshots and the diff engine only.
Persistence (save/load), UI surfaces and CLI commands are separate,
not-yet-built features.
"""

from .diff import diff_snapshot
from .export import (
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
from .matching import new_process_refs, new_socket_identities
from .models import (
    CATEGORY_PACKAGE,
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
    CHANGE_NEW,
    CHANGE_REMOVED,
    SEVERITY_INFO,
    BaselineSnapshot,
    DriftEvent,
    DriftReport,
    PackageIdentity,
    ProcessRef,
    SocketIdentity,
)
from .snapshot import build_snapshot

__all__ = [
    "CATEGORY_PACKAGE",
    "CATEGORY_PROCESS",
    "CATEGORY_SOCKET",
    "CHANGE_NEW",
    "CHANGE_REMOVED",
    "SEVERITY_INFO",
    "BaselineSnapshot",
    "DriftEvent",
    "DriftReport",
    "PackageIdentity",
    "ProcessRef",
    "Session",
    "SocketIdentity",
    "build_snapshot",
    "diff_snapshot",
    "drift_event_from_dict",
    "drift_event_to_dict",
    "drift_events_to_csv",
    "drift_report_from_dict",
    "drift_report_to_dict",
    "from_json",
    "new_process_refs",
    "new_socket_identities",
    "session_from_dict",
    "session_to_dict",
    "snapshot_from_dict",
    "snapshot_to_dict",
    "to_json",
    "write_drift_events_csv",
    "write_session_json",
]