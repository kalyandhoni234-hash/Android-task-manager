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
    "SocketIdentity",
    "build_snapshot",
    "diff_snapshot",
]