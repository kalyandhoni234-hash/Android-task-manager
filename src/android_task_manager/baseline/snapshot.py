"""Baseline snapshot builder — a pure transformation over collected data.

Takes the already-collected, already-normalized frozen dataclasses that the
existing collectors produce (process rows, the PackageResolver's installed
set, the network-investigation snapshot) and reshapes them into the
identity-only :class:`BaselineSnapshot` form used by the diff engine.

This module never calls ``ConnectionManager``, never invokes ``subprocess``
and never reads from the device: it is a pure function over in-memory data,
fully unit-testable with constructed fixtures.

Verification flags:
    * ``sockets_verified`` defaults to the investigation snapshot's own
      ``source_available`` — the collector's real read-status signal
      (``False`` when the device refused the socket-table reads).
    * ``processes_verified`` / ``packages_verified`` default to ``True``
      because the collectors surface failed reads as typed ADB errors instead
      of returning partial data (the process collector raises on a failed
      ``ps``; the PackageResolver only ever holds verified installed lists).
      Pass ``False`` explicitly when the caller has knowledge of an
      incomplete read — the diff engine then refuses to diff that category
      instead of diffing unreliable data.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import datetime, timezone

from ..network_investigation.models import NetworkInvestigationSnapshot
from ..process.models import ProcessInfo
from .models import (
    BaselineSnapshot,
    PackageIdentity,
    ProcessRef,
    SocketIdentity,
)

#: Collector-generated placeholder for processes `top` saw but `ps` never
#: identified (name embeds the PID). Such rows have no stable identity — a
#: restarted process gets a *different* placeholder — so they cannot be
#: diffed honestly and are excluded.
_PLACEHOLDER_NAME_RE = re.compile(r"^<pid \d+>$")


def build_snapshot(
    device_serial: str,
    processes: Iterable[ProcessInfo],
    installed_packages: Collection[str],
    uid_packages: Mapping[int, Sequence[str]] | None = None,
    sockets: NetworkInvestigationSnapshot | None = None,
    *,
    processes_verified: bool = True,
    packages_verified: bool = True,
    sockets_verified: bool | None = None,
    created_at: datetime | None = None,
) -> BaselineSnapshot:
    """Build an identity-only :class:`BaselineSnapshot` from collected data.

    Args:
        device_serial: The adb serial the data was collected from.
        processes: ``ProcessInfo`` rows (e.g. ``ProcessSnapshot.processes``).
        installed_packages: Verified installed package names (e.g.
            ``PackageResolver.installed()``).
        uid_packages: Optional UID → packages map (e.g.
            ``NetworkInvestigationSnapshot.uid_packages`` from ``pm list
            packages -U``). Names without a UID map as ``uid=None``.
        sockets: Optional investigation snapshot. ``None`` (or an
            unavailable source) implies an unverified socket category.
        processes_verified / packages_verified: Whether those reads fully
            succeeded (pass ``False`` when a read was incomplete).
        sockets_verified: Defaults to ``sockets.source_available``; pass an
            explicit value to override.
        created_at: Snapshot timestamp (defaults to now, UTC — pass a fixed
            value for deterministic tests).
    """
    process_refs = frozenset(
        ProcessRef(uid=info.uid, process_name=info.name, classification=info.category)
        for info in processes
        if not _PLACEHOLDER_NAME_RE.search((info.name or "").strip())
    )

    uid_by_package = _uid_by_package(uid_packages)
    package_identities = frozenset(
        PackageIdentity(package_name=name, uid=uid_by_package.get(name))
        for name in installed_packages
    )

    if sockets is None:
        socket_identities: frozenset[SocketIdentity] = frozenset()
        effective_sockets_verified = False
    else:
        # Rows without an address or port carry no stable key and are
        # excluded; zero is only ever a real kernel value, so port 0 is kept.
        socket_identities = frozenset(
            SocketIdentity(
                protocol=socket.protocol,
                local_address=socket.local_address,
                local_port=socket.local_port,
                uid=socket.uid,
            )
            for socket in sockets.sockets
            if socket.local_address is not None and socket.local_port is not None
        )
        effective_sockets_verified = (
            sockets.source_available
            if sockets_verified is None
            else sockets_verified
        )

    return BaselineSnapshot(
        created_at=created_at or datetime.now(timezone.utc),
        device_serial=device_serial,
        processes=process_refs,
        packages=package_identities,
        sockets=socket_identities,
        processes_verified=processes_verified,
        packages_verified=packages_verified,
        sockets_verified=effective_sockets_verified,
    )


def _uid_by_package(
    uid_packages: Mapping[int, Sequence[str]] | None,
) -> dict[str, int | None]:
    """Invert the UID → packages map into name → uid.

    A package that maps to exactly one UID keeps it. A name under several
    UIDs (not expected in practice) resolves to ``None``: choosing one would
    fabricate an attribution.
    """
    if not uid_packages:
        return {}
    name_to_uids: dict[str, set[int]] = {}
    for uid, names in uid_packages.items():
        for name in names:
            name_to_uids.setdefault(name, set()).add(uid)
    return {
        name: (next(iter(uids)) if len(uids) == 1 else None)
        for name, uids in name_to_uids.items()
    }