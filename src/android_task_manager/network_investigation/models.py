"""Typed, normalized snapshot for per-process network investigation.

Read this alongside ``docs/m14-network-research.md``: on a non-root Android
device every field here is either device-verified or honestly ``None``.

Attribution model (evidence-based, never fabricated):

* **UID** — the socket tables' uid column (verified on the Vivo).
* **Package** — UID → installed packages from ``pm list packages -U``
  (verified). Multiple packages may share one UID; all of them are kept.
* **PID** — the kernel exposes no PID per socket, ``/proc/<pid>/fd`` is
  permission-denied to adb-shell and netlink diag is blocked, so on this
  device stack PID stays ``None``; the model carries the field only so a
  future source that *can* provide it is accepted without inventing one.
  The UI states that attribution is UID-level, never PID-level.
* **Interface** — no non-root source associates a socket with an interface;
  the model carries no interface field instead of a guessed one.

``None`` means "unavailable" everywhere; zero is only a real kernel value
(e.g. a UDP remote of ``0.0.0.0:0`` is displayed as such, not fabricated).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SocketInfo:
    """One socket row observed in a ``/proc/net/{tcp,tcp6,udp,udp6}`` table.

    ``state`` is only meaningful for TCP; UDP sockets (and a handful of
    kernel markers) leave it ``None`` rather than borrowing TCP semantics.
    """

    protocol: str
    family: str
    local_address: str | None = None
    local_port: int | None = None
    remote_address: str | None = None
    remote_port: int | None = None
    state: str | None = None
    uid: int | None = None
    inode: int | None = None
    #: Owning PID when a source actually provided one; ``None`` on the
    #: standard non-root stack (never derived or guessed).
    pid: int | None = None


@dataclass(frozen=True)
class NetworkInvestigationSnapshot:
    """The complete socket-level view obtained in one collection pass.

    ``source_available`` distinguishes "the device refused the reads"
    from "the tables were read and simply held no sockets" — the UI must
    show those two states differently.
    """

    timestamp: float = 0.0
    sockets: tuple[SocketInfo, ...] = ()
    source_available: bool = False
    source_errors: tuple[str, ...] = ()
    uid_packages: dict[int, tuple[str, ...]] = field(default_factory=dict)

    def sockets_for_uid(self, uid: int) -> tuple[SocketInfo, ...]:
        """Sockets owned by *uid* (the only evidence-based attribution)."""
        if uid is None:
            return ()
        return tuple(s for s in self.sockets if s.uid == uid)

    def packages_for_uid(self, uid: int) -> tuple[str, ...]:
        """Installed packages sharing *uid*, or ``()`` when none is known."""
        return self.uid_packages.get(uid, ())