"""Identity projection helpers for drift-driven UI highlighting.

This is a small convenience layer added for the GUI integration task (flagged
in that task's summary as the explicitly-allowed smallest possible backend
addition): UI surfaces need to know *which identities* a drift report's NEW
events refer to, and the report itself carries only human-readable
descriptions (``entity`` / ``current_value`` strings), not the typed
identity objects. Deriving the identity sets from the two snapshots the
caller already holds is fact-exact — the module reuses the same frozenset
difference the diff engine applied — and avoids parsing display strings.

Honesty rule (mirrors the diff engine): when a category was not fully
verified on either side it is listed in ``DriftReport.unverified_categories``
and was never diffed, so the projection returns an empty set instead of
highlighting rows based on unverified data.
"""

from __future__ import annotations

from .models import (
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
    BaselineSnapshot,
    DriftReport,
    ProcessRef,
    SocketIdentity,
)


def new_process_refs(
    report: DriftReport,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
) -> frozenset[ProcessRef]:
    """The process identities that are NEW in *current* vs *baseline*.

    Empty when the process category was not fully verified on both sides
    (the diff engine then emitted no process events at all).
    """
    if CATEGORY_PROCESS in report.unverified_categories:
        return frozenset()
    return current.processes - baseline.processes


def new_socket_identities(
    report: DriftReport,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
) -> frozenset[SocketIdentity]:
    """The socket identities that are NEW in *current* vs *baseline*.

    Same verification guard as :func:`new_process_refs`.
    """
    if CATEGORY_SOCKET in report.unverified_categories:
        return frozenset()
    return current.sockets - baseline.sockets