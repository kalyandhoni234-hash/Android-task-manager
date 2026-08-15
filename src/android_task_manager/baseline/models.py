"""Baseline drift detection — data models.

A *baseline snapshot* is an identity-only view of device state (processes,
packages, listening sockets) captured at one moment. The diff engine
(``baseline/diff.py``) compares two snapshots and reports *facts only*: what
is new and what is gone. Nothing here judges importance — every emitted
event has ``INFO`` severity by design, because risk/heuristics are an
explicitly separate, later concern.

Identity rule (critical): identities are stable (UID + name), never
PID-based. PIDs are reused across process restarts and would produce false
positives when e.g. a browser restarts with a new PID.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..process.models import ProcessCategory

#: Drift categories — keys used across snapshots, events and reports.
CATEGORY_PROCESS = "process"
CATEGORY_PACKAGE = "package"
CATEGORY_SOCKET = "socket"

#: Structural change types. Only NEW/REMOVED exist in this phase; behavioral
#: state-change diffing (e.g. a command-line change) is a later concern.
CHANGE_NEW = "NEW"
CHANGE_REMOVED = "REMOVED"

#: Severity is a constant today: the diff engine reports facts and never
#: scores them. Risk assessment is an explicitly separate future feature.
SEVERITY_INFO = "INFO"


@dataclass(frozen=True)
class ProcessRef:
    """A stable process identity — deliberately **not** PID-based.

    PIDs are reused after process restarts, so the identity is (uid,
    process_name, classification). ``uid`` may be ``None`` for processes the
    authoritative ``ps`` identity did not cover (top-only rows): that state
    is kept honest, never guessed.
    """

    uid: int | None
    process_name: str
    classification: ProcessCategory


@dataclass(frozen=True)
class PackageIdentity:
    """An installed package identity (name, uid).

    UIDs come from the separate ``pm list packages -U`` read; when only the
    plain installed list was verified (or a name maps to several UIDs),
    ``uid`` stays ``None`` — name-only identity is diffed, never fabricated.
    """

    package_name: str
    uid: int | None


@dataclass(frozen=True)
class SocketIdentity:
    """A listening/hosted socket identity from the four /proc/net tables.

    ``uid`` is ``None`` when socket ownership could not be attributed — the
    diff engine must not invent one.
    """

    protocol: str  # "tcp" | "tcp6" | "udp" | "udp6" (as SocketInfo reports it)
    local_address: str
    local_port: int
    uid: int | None = None


@dataclass(frozen=True)
class BaselineSnapshot:
    """An identity-only snapshot of device state at one moment.

    The ``*_verified`` flags record whether each category's underlying read
    fully succeeded. The diff engine requires both sides verified per
    category; otherwise it reports the category as unverified instead of
    diffing incomplete data.
    """

    created_at: datetime
    device_serial: str
    processes: frozenset[ProcessRef] = frozenset()
    packages: frozenset[PackageIdentity] = frozenset()
    sockets: frozenset[SocketIdentity] = frozenset()
    processes_verified: bool = True
    packages_verified: bool = True
    sockets_verified: bool = True


@dataclass(frozen=True)
class DriftEvent:
    """One structural fact: an entity is NEW or REMOVED relative to a baseline.

    ``severity`` is always ``INFO`` — this task deliberately contains no
    risk/heuristic logic.
    """

    category: str  # CATEGORY_PROCESS | CATEGORY_PACKAGE | CATEGORY_SOCKET
    change_type: str  # CHANGE_NEW | CHANGE_REMOVED
    severity: str = SEVERITY_INFO
    entity: str = ""
    baseline_value: str | None = None
    current_value: str | None = None
    explanation: str = ""


@dataclass(frozen=True)
class DriftReport:
    """The result of comparing baseline and current snapshots."""

    baseline_created_at: datetime
    compared_at: datetime
    events: tuple[DriftEvent, ...] = ()
    #: Categories left undiffed because at least one side's read was
    #: incomplete — each appears at most once, in a fixed order.
    unverified_categories: tuple[str, ...] = ()