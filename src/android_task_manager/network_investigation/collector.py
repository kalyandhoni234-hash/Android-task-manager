"""Collector that reads the four socket tables plus the UID→package map.

The investigation collector performs exactly one pass per sample: four
``cat /proc/net/{tcp,tcp6,udp,udp6}`` reads plus one
``pm list packages -U`` call. There are deliberately **no per-process**
commands — the tables already carry the UID, which is the only
evidence-based attribution link (see ``docs/m14-network-research.md``).

Each table is read independently: a permission failure on one table must not
hide the sockets visible in the others, so per-file failures are recorded in
``source_errors`` and ``source_available`` reflects whether at least one
table actually produced kernel data. All I/O goes through the injectable
runner — never ``subprocess``.
"""

from __future__ import annotations

import time

from ..adb.exceptions import (
    ADBCommandError,
    ADBDisconnectedError,
    ADBError,
    ADBNoDeviceError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)
from .models import NetworkInvestigationSnapshot, SocketInfo
from .parser import SocketTableParseError, parse_socket_table, parse_uid_packages

#: (path, protocol, family) for the four socket tables.
_SOCKET_TABLES: tuple[tuple[str, str, str], ...] = (
    ("/proc/net/tcp", "tcp", "ipv4"),
    ("/proc/net/tcp6", "tcp", "ipv6"),
    ("/proc/net/udp", "udp", "ipv4"),
    ("/proc/net/udp6", "udp", "ipv6"),
)

#: Failures that mean the connection itself is broken: they must propagate
#: to the monitor's state machine. Non-zero-exit responses (e.g. a denied
#: ``cat``) instead degrade to partial ``source_errors``.
_CONNECTION_FAILURES = (
    ADBDisconnectedError,
    ADBNoDeviceError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)


class NetworkInvestigationCollector:
    """Samples the socket tables and the package map in one bound pass."""

    def __init__(self, runner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def sample(self) -> NetworkInvestigationSnapshot:
        """Read all tables and assemble a fresh snapshot.

        Failures are collected per table instead of aborting: the snapshot
        then honestly shows partial data plus its ``source_errors``. Only
        connection-level failures (offline/timeout/unauthorized) propagate.
        """
        sockets: list[SocketInfo] = []
        errors: list[str] = []
        read_ok = 0

        for path, protocol, family in _SOCKET_TABLES:
            try:
                text = self._runner.shell(["cat", path], timeout=self._timeout)
                table_sockets = parse_socket_table(text, protocol, family)
            except _CONNECTION_FAILURES:
                raise
            except (ADBError, SocketTableParseError) as exc:
                errors.append(f"{path}: {exc}")
                continue
            sockets.extend(table_sockets)
            read_ok += 1

        uid_packages: dict[int, tuple[str, ...]] = {}
        try:
            package_map = self._runner.shell(
                ["pm", "list", "packages", "-U"], timeout=self._timeout
            )
        except _CONNECTION_FAILURES:
            raise
        except ADBError as exc:
            errors.append(f"pm list packages -U: {exc}")
        else:
            uid_packages = parse_uid_packages(package_map)

        return NetworkInvestigationSnapshot(
            timestamp=time.monotonic(),
            sockets=tuple(sockets),
            source_available=read_ok > 0,
            source_errors=tuple(errors),
            uid_packages=uid_packages,
        )