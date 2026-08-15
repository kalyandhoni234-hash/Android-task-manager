"""Snapshot completeness — COMPLETE / PARTIAL / FAILED determination.

The existing pipeline already records per-category ``*_verified`` flags on
:class:`BaselineSnapshot` and ``source_available`` on
:class:`NetworkInvestigationSnapshot`. This module turns those flags into
the three-state completeness model the stability analysis needs, with one
rule: **absence is only meaningful from a COMPLETE read**.

Derivation (purely from collected data, no assumptions about the device):

* verified / available          -> COMPLETE
* unverified but data present   -> PARTIAL  (a partial read, not a claim)
* unverified and nothing read   -> FAILED   (never compared as "empty")
"""

from __future__ import annotations

from ..baseline.models import (
    CATEGORY_PACKAGE,
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
    BaselineSnapshot,
)
from ..network_investigation.models import NetworkInvestigationSnapshot
from .models import SnapshotCompleteness


def snapshot_completeness(*, verified: bool, has_items: bool) -> SnapshotCompleteness:
    """Derive a category's completeness from its verified flag and content."""
    if verified:
        return SnapshotCompleteness.COMPLETE
    return SnapshotCompleteness.PARTIAL if has_items else SnapshotCompleteness.FAILED


def baseline_category_completeness(
    snapshot: BaselineSnapshot,
    category: str,
) -> SnapshotCompleteness:
    """Completeness of one category of a baseline snapshot."""
    if category == CATEGORY_PROCESS:
        return snapshot_completeness(
            verified=snapshot.processes_verified,
            has_items=bool(snapshot.processes),
        )
    if category == CATEGORY_PACKAGE:
        return snapshot_completeness(
            verified=snapshot.packages_verified,
            has_items=bool(snapshot.packages),
        )
    if category == CATEGORY_SOCKET:
        return snapshot_completeness(
            verified=snapshot.sockets_verified,
            has_items=bool(snapshot.sockets),
        )
    return SnapshotCompleteness.FAILED


def socket_table_completeness(
    snapshot: NetworkInvestigationSnapshot | None,
) -> SnapshotCompleteness:
    """Completeness of the socket tables from the investigation collector.

    ``source_available`` distinguishes "the device refused the reads"
    (FAILED) from "the tables were read and simply held no sockets"
    (COMPLETE); a partial read with some rows is PARTIAL.
    """
    if snapshot is None:
        return SnapshotCompleteness.FAILED
    if snapshot.source_available:
        return SnapshotCompleteness.COMPLETE
    return SnapshotCompleteness.PARTIAL if snapshot.sockets else SnapshotCompleteness.FAILED


__all__ = [
    "baseline_category_completeness",
    "snapshot_completeness",
    "socket_table_completeness",
]