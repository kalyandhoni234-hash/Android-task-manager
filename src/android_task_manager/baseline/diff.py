"""Baseline diff engine — pure, facts-only comparisons.

:func:`diff_snapshot` compares two :class:`BaselineSnapshot` values and emits
exactly two kinds of structural facts per category: **NEW** (present in the
current snapshot, absent in the baseline) and **REMOVED** (present in the
baseline, gone now). It never judges *why* a change matters: every event has
``INFO`` severity, because heuristics and risk assessment are an explicitly
separate, later feature.

Unverified data is never diffed: when either snapshot marks a category as
not fully verified, that category lands in
``DriftReport.unverified_categories`` ("could not verify") instead of
producing potentially-misleading events.

The function is pure: no I/O, no ADB, no side effects — fully unit-testable
with in-memory fixture snapshots.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

from .models import (
    CATEGORY_PACKAGE,
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
    CHANGE_NEW,
    CHANGE_REMOVED,
    BaselineSnapshot,
    DriftEvent,
    DriftReport,
    PackageIdentity,
    ProcessRef,
    SocketIdentity,
)

_T = TypeVar("_T")


def diff_snapshot(
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    *,
    compared_at: datetime | None = None,
) -> DriftReport:
    """Compare *current* against *baseline* and report structural drift facts.

    Events are sorted by (category, change_type, entity) so output and tests
    are stable. Categories whose data was not fully verified on either side
    are listed in ``unverified_categories`` and never diffed.
    """
    events: list[DriftEvent] = []
    unverified: list[str] = []

    _diff_processes(baseline, current, events, unverified)
    _diff_packages(baseline, current, events, unverified)
    _diff_sockets(baseline, current, events, unverified)

    events.sort(key=lambda event: (event.category, event.change_type, event.entity))
    return DriftReport(
        baseline_created_at=baseline.created_at,
        compared_at=compared_at or datetime.now(timezone.utc),
        events=tuple(events),
        unverified_categories=tuple(unverified),
    )


# ---------------------------------------------------------------------------
# Per-category diff wrappers (fully typed per identity type).
# ---------------------------------------------------------------------------

#: (new explanation, removed explanation) per category.
_EXPLANATIONS: dict[str, tuple[str, str]] = {
    CATEGORY_PROCESS: ("New process observed", "Process no longer observed"),
    CATEGORY_PACKAGE: ("New package installed", "Package no longer installed"),
    CATEGORY_SOCKET: ("New listening socket detected", "Listening socket no longer observed"),
}


def _diff_processes(
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    events: list[DriftEvent],
    unverified: list[str],
) -> None:
    _diff_category(
        category=CATEGORY_PROCESS,
        baseline_verified=baseline.processes_verified,
        current_verified=current.processes_verified,
        baseline_items=baseline.processes,
        current_items=current.processes,
        sort_key=_process_sort_key,
        entity_of=lambda identity: identity.process_name,
        describe=_describe_process,
        explanations=_EXPLANATIONS[CATEGORY_PROCESS],
        events=events,
        unverified=unverified,
    )


def _diff_packages(
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    events: list[DriftEvent],
    unverified: list[str],
) -> None:
    _diff_category(
        category=CATEGORY_PACKAGE,
        baseline_verified=baseline.packages_verified,
        current_verified=current.packages_verified,
        baseline_items=baseline.packages,
        current_items=current.packages,
        sort_key=_package_sort_key,
        entity_of=lambda identity: identity.package_name,
        describe=_describe_package,
        explanations=_EXPLANATIONS[CATEGORY_PACKAGE],
        events=events,
        unverified=unverified,
    )


def _diff_sockets(
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    events: list[DriftEvent],
    unverified: list[str],
) -> None:
    _diff_category(
        category=CATEGORY_SOCKET,
        baseline_verified=baseline.sockets_verified,
        current_verified=current.sockets_verified,
        baseline_items=baseline.sockets,
        current_items=current.sockets,
        sort_key=_socket_sort_key,
        entity_of=_socket_entity,
        describe=_describe_socket,
        explanations=_EXPLANATIONS[CATEGORY_SOCKET],
        events=events,
        unverified=unverified,
    )


# ---------------------------------------------------------------------------
# Per-category rendering.
# ---------------------------------------------------------------------------


def _uid_key(uid: int | None) -> int:
    """Sort key for optional UIDs: ``None`` sorts before any real UID."""
    return -1 if uid is None else uid


def _process_sort_key(identity: ProcessRef) -> tuple:
    return (identity.process_name, _uid_key(identity.uid), identity.classification.value)


def _package_sort_key(identity: PackageIdentity) -> tuple:
    return (identity.package_name, _uid_key(identity.uid))


def _socket_sort_key(identity: SocketIdentity) -> tuple:
    return (identity.protocol, identity.local_address, identity.local_port, _uid_key(identity.uid))


def _describe_process(identity: ProcessRef) -> str:
    uid = "unknown" if identity.uid is None else str(identity.uid)
    return f"{identity.process_name} (uid {uid}, {identity.classification.value})"


def _describe_package(identity: PackageIdentity) -> str:
    uid = "unknown" if identity.uid is None else str(identity.uid)
    return f"{identity.package_name} (uid {uid})"


def _socket_entity(identity: SocketIdentity) -> str:
    return f"{identity.protocol}:{identity.local_address}:{identity.local_port}"


def _describe_socket(identity: SocketIdentity) -> str:
    entity = _socket_entity(identity)
    return entity if identity.uid is None else f"{entity} (uid {identity.uid})"


# ---------------------------------------------------------------------------
# Category-agnostic diff worker.
# ---------------------------------------------------------------------------


def _diff_category(
    *,
    category: str,
    baseline_verified: bool,
    current_verified: bool,
    baseline_items: frozenset[_T],
    current_items: frozenset[_T],
    sort_key: Callable[[_T], tuple],
    entity_of: Callable[[_T], str],
    describe: Callable[[_T], str],
    explanations: tuple[str, str],
    events: list[DriftEvent],
    unverified: list[str],
) -> None:
    """Emit NEW/REMOVED events for one category, or mark it unverified.

    The category is only diffed when **both** snapshots verified it: diffing
    a partially-read set would fabricate a "no change" reading.
    """
    if not (baseline_verified and current_verified):
        unverified.append(category)
        return

    new_explanation, removed_explanation = explanations
    for identity in sorted(current_items - baseline_items, key=sort_key):
        events.append(
            DriftEvent(
                category=category,
                change_type=CHANGE_NEW,
                entity=entity_of(identity),
                current_value=describe(identity),
                explanation=new_explanation,
            )
        )
    for identity in sorted(baseline_items - current_items, key=sort_key):
        events.append(
            DriftEvent(
                category=category,
                change_type=CHANGE_REMOVED,
                entity=entity_of(identity),
                baseline_value=describe(identity),
                explanation=removed_explanation,
            )
        )