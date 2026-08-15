"""Network → process → package attribution.

Resolves one socket's ownership chain from already-collected data:

    SOCKET → PID → PROCESS → UID → PACKAGE

The result is labeled with an explicit honesty state:

* FULL — every link resolved (socket → PID → process → package).
* PARTIAL — socket → UID (optionally UID → package). UID-level
  attribution is never labeled package-level.
* UNAVAILABLE — no reliable owner was collected.

On a non-root Android device the socket tables expose a UID but no PID
(``/proc/<pid>/fd`` is permission-denied to adb-shell), so real-device
rows are normally PARTIAL. FULL is only claimed when the caller has
actual PID data (e.g. a future collector or a device where it exists) —
never invented. No external lookups: everything comes from the snapshots
already in memory.
"""

from __future__ import annotations

from ..baseline.models import (
    CHANGE_NEW,
    CHANGE_REMOVED,
    BaselineSnapshot,
    SocketIdentity,
)
from ..process.models import ProcessSnapshot
from .models import AttributionState, SocketAttribution


def _socket_entity(identity: SocketIdentity) -> str:
    return f"{identity.protocol}:{identity.local_address}:{identity.local_port}"


def _baseline_status(
    socket: SocketIdentity,
    baseline: BaselineSnapshot | None,
    current: BaselineSnapshot | None,
) -> str:
    if baseline is None or current is None:
        return "BASELINE"
    in_baseline = socket in baseline.sockets
    in_current = socket in current.sockets
    if in_current and in_baseline:
        return "BASELINE"
    if in_current:
        return CHANGE_NEW
    if in_baseline:
        return CHANGE_REMOVED
    return "BASELINE"


def _package_names(
    uid: int | None,
    uid_packages: dict[int, tuple[str, ...]] | None,
    current: BaselineSnapshot | None,
) -> tuple[str, ...]:
    """Package names for *uid*: the investigation snapshot's map is
    authoritative, with the current snapshot's package list as fallback."""
    if uid is None:
        return ()
    if uid_packages:
        return tuple(sorted(uid_packages.get(uid, ())))
    if current is not None:
        return tuple(sorted(p.package_name for p in current.packages if p.uid == uid))
    return ()


def attribute_socket(
    socket: SocketIdentity,
    *,
    pid: int | None = None,
    processes: ProcessSnapshot | None = None,
    uid_packages: dict[int, tuple[str, ...]] | None = None,
    baseline: BaselineSnapshot | None = None,
    current: BaselineSnapshot | None = None,
    first_observed: float | None = None,
) -> SocketAttribution:
    """Attribute one socket's ownership chain, honestly labeled.

    ``pid`` must come from collected data (it is never derived here).
    The chain is only FULL when every link resolves and the UID agrees;
    a UID conflict between the socket table and the process row prevents
    FULL attribution rather than guessing which is right.
    """
    uid = socket.uid
    process_name: str | None = None
    process_uid: int | None = None

    if pid is not None and processes is not None:
        info = next((p for p in processes.processes if p.pid == pid), None)
        if info is not None:
            process_name = info.name
            process_uid = info.uid

    if process_name is not None and (uid is None or process_uid == uid):
        resolved_uid = uid if uid is not None else process_uid
        packages = _package_names(resolved_uid, uid_packages, current)
        if packages:
            return SocketAttribution(
                socket=socket,
                attribution_state=AttributionState.FULL,
                pid=pid,
                process_name=process_name,
                uid=resolved_uid,
                package_names=packages,
                baseline_status=_baseline_status(socket, baseline, current),
                first_observed=first_observed,
            )
        return SocketAttribution(
            socket=socket,
            attribution_state=AttributionState.PARTIAL,
            pid=pid,
            process_name=process_name,
            uid=resolved_uid,
            package_names=(),
            baseline_status=_baseline_status(socket, baseline, current),
            first_observed=first_observed,
        )

    if uid is not None:
        return SocketAttribution(
            socket=socket,
            attribution_state=AttributionState.PARTIAL,
            uid=uid,
            package_names=_package_names(uid, uid_packages, current),
            baseline_status=_baseline_status(socket, baseline, current),
            first_observed=first_observed,
        )

    return SocketAttribution(
        socket=socket,
        attribution_state=AttributionState.UNAVAILABLE,
        baseline_status=_baseline_status(socket, baseline, current),
        first_observed=first_observed,
    )


def attribute_sockets(
    sockets: tuple[SocketIdentity, ...],
    *,
    pid_by_entity: dict[str, int] | None = None,
    processes: ProcessSnapshot | None = None,
    uid_packages: dict[int, tuple[str, ...]] | None = None,
    baseline: BaselineSnapshot | None = None,
    current: BaselineSnapshot | None = None,
    first_observed_by_entity: dict[str, float] | None = None,
) -> tuple[SocketAttribution, ...]:
    """Attribute a set of sockets in deterministic (entity) order."""
    pid_by_entity = pid_by_entity or {}
    first_observed_by_entity = first_observed_by_entity or {}
    ordered = sorted(
        sockets,
        key=lambda s: (s.protocol, s.local_address, s.local_port, -1 if s.uid is None else s.uid),
    )
    return tuple(
        attribute_socket(
            socket,
            pid=pid_by_entity.get(_socket_entity(socket)),
            processes=processes,
            uid_packages=uid_packages,
            baseline=baseline,
            current=current,
            first_observed=first_observed_by_entity.get(_socket_entity(socket)),
        )
        for socket in ordered
    )


__all__ = [
    "attribute_socket",
    "attribute_sockets",
]