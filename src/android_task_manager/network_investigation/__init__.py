"""Per-process network investigation: socket tables, UID attribution.

M14 — non-root read-only visibility into which sockets exist on the device
(TCP/UDP, IPv4/IPv6), grouped by the only evidence-based attribution the
device exposes: the socket owner UID mapped to installed packages.

Read ``docs/m14-network-research.md`` for the capability inventory and
the deliberate absence of PID/interface attribution.
"""

from .collector import NetworkInvestigationCollector
from .models import NetworkInvestigationSnapshot, SocketInfo
from .parser import (
    TCP_STATES,
    SocketTableParseError,
    parse_socket_table,
    parse_uid_packages,
)

__all__ = [
    "NetworkInvestigationCollector",
    "NetworkInvestigationSnapshot",
    "SocketInfo",
    "SocketTableParseError",
    "TCP_STATES",
    "parse_socket_table",
    "parse_uid_packages",
]