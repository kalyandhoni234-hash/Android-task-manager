"""Parser for the Linux socket tables readable on a non-root Android device.

The tables ``/proc/net/{tcp,tcp6,udp,udp6}`` share one row layout with two
diagnosed variants: the stock kernel prints

``sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt
uid timeout inode [ref pointer drops]``

where the two queue pairs collapse into single ``tx:rx`` and ``tr:tm``
tokens, so a data row is

``0: A6055664:C4F2 62648626:01BB 04 00000001:00000000 00:00000000
00000000 0 0 0 1 0000000000000000 72 4 30 10 -1``

while some kernels (observed on the Vivo V2026) append extra trailing
tokens after the pointer on the TCP tables. In every observed layout the
**uid, timeout and inode columns sit at token indexes 7, 8 and 9** (verified
against real device output where live uids such as 1000, 10181, 10203 were
lost-free at index 7 across tcp/tcp6/udp/udp6). The parser therefore anchors
on those indexes and additionally requires each to be a plain decimal, so a
foreign kernel layout degrades by skipping rows rather than attributing
wrongly.

Malformed rows are skipped instead of failing the whole parse, mirroring
``network.parser``: one broken row must not hide healthy ones. Only when the
input contains neither a recognizable header nor a single parseable row is
:class:`SocketTableParseError` raised.
"""

from __future__ import annotations

import re

from ..action.package import PackageValidationError, validate_package_name
from .models import SocketInfo

#: Recognized state values from the IPv4/IPv6 TCP state machine.
#: Values outside this map (observable on unusual kernels) are kept as their
#: raw two-hex-digit string instead of failing the row.
TCP_STATES: dict[str, str] = {
    "01": "ESTABLISHED",
    "02": "SYN-SENT",
    "03": "SYN-RECV",
    "04": "FIN-WAIT-1",
    "05": "FIN-WAIT-2",
    "06": "TIME-WAIT",
    "07": "CLOSE",
    "08": "CLOSE-WAIT",
    "09": "LAST-ACK",
    "0A": "LISTEN",
    "0B": "CLOSING",
}

#: One address:port token, e.g. ``A6055664:C4F2`` (IPv4) or the 32-hex
#: IPv6 form. Rejects anything that could not be a socket table column.
_ADDR_PORT_RE = re.compile(r"^[0-9A-Fa-f]{8}([0-9A-Fa-f]{24})?:[0-9A-Fa-f]{1,4}$")

#: Prefix of a v4-mapped IPv6 address (``::ffff:a.b.c.d``) as printed by the
#: kernel for IPv4 sockets on the tcp6/udp6 tables (first four groups zeroed,
#: then ``ffff:0``, then the v4 bytes).
_V4_MAPPED_PREFIX = "0000000000000000FFFF0000"


class SocketTableParseError(ValueError):
    """Raised when the input is not recognizable socket-table content."""


def _decode_ipv4(hex_addr: str) -> str:
    """Decode a little-endian 8-hex IPv4 address like ``A6055664``."""
    raw = int(hex_addr, 16).to_bytes(4, byteorder="little")
    return ".".join(str(byte) for byte in raw)


def _decode_ipv6(hex_addr: str) -> str:
    """Decode a little-endian 32-hex IPv6 address into standard notation.

    Each of the eight 16-bit groups is stored little-endian, so the group
    bytes are reversed before formatting (observed live on the Vivo).
    """
    groups: list[str] = []
    for offset in range(0, 32, 8):
        group_bytes = int(hex_addr[offset : offset + 8], 16).to_bytes(4, byteorder="little")
        hi, lo = (int.from_bytes(group_bytes[:2], "big"), int.from_bytes(group_bytes[2:], "big"))
        groups.append(f"{hi:04x}:{lo:04x}")
    return ":".join(groups)


def _decode_address(hex_addr: str, family: str) -> tuple[str, str]:
    """Return ``(family, address_text)`` honoring v4-mapped IPv6 rows."""
    if hex_addr.startswith(_V4_MAPPED_PREFIX):
        return "ipv4", _decode_ipv4(hex_addr[len(_V4_MAPPED_PREFIX) :])
    if family == "ipv6":
        return "ipv6", _decode_ipv6(hex_addr)
    return "ipv4", _decode_ipv4(hex_addr)


def parse_socket_table(text: str, protocol: str, family: str) -> list[SocketInfo]:
    """Parse one raw ``/proc/net/*`` table into normalized socket rows.

    :param text: Raw device output of one socket table.
    :param protocol: ``"tcp"`` or ``"udp"``.
    :param family: ``"ipv4"`` or ``"ipv6"``.
    :return: One :class:`SocketInfo` per parseable data row, in file order.
    :raises SocketTableParseError: If the input has neither a header nor a
        single parseable row.
    """
    if protocol not in ("tcp", "udp") or family not in ("ipv4", "ipv6"):
        raise SocketTableParseError("invalid socket table type")

    sockets: list[SocketInfo] = []
    header_seen = False

    for raw_line in text.splitlines():
        tokens = raw_line.split()
        if not tokens:
            continue
        if tokens[0].lower() == "sl":
            header_seen = True
            continue
        if len(tokens) < 10:
            continue
        if not tokens[0].endswith(":"):
            continue
        if not _ADDR_PORT_RE.fullmatch(tokens[1]) or not _ADDR_PORT_RE.fullmatch(tokens[2]):
            continue

        try:
            uid = int(tokens[7])
            timeout = int(tokens[8])
            inode = int(tokens[9])
            if uid < 0 or timeout < 0 or inode < 0:
                raise ValueError
        except ValueError:
            continue

        local_family, local_address = _decode_address(tokens[1][:-5], family)
        remote_family, remote_address = _decode_address(tokens[2][:-5], family)
        if local_family != remote_family:
            continue
        row_family = local_family

        local_port = int(tokens[1][-4:], 16)
        remote_port = int(tokens[2][-4:], 16)

        state: str | None = None
        if protocol == "tcp":
            state = TCP_STATES.get(tokens[3].upper(), tokens[3].upper())

        sockets.append(
            SocketInfo(
                protocol=protocol,
                family=row_family,
                local_address=local_address,
                local_port=local_port,
                remote_address=remote_address,
                remote_port=remote_port,
                state=state,
                uid=uid,
                inode=inode,
            )
        )

    if not sockets and not header_seen:
        raise SocketTableParseError(
            f"Not /proc/net/{protocol}{family[-1] if family == 'ipv6' else ''} content: no header or rows"
        )

    return sockets


def parse_uid_packages(text: str) -> dict[int, tuple[str, ...]]:
    """Parse ``pm list packages -U`` output into ``{uid: (packages, ...)}``.

    Only lines of the form ``package:<name> uid:<number>`` that survive
    strict package validation are kept; anything else is skipped rather than
    failing the whole read.
    """
    uid_packages: dict[int, tuple[str, ...]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("package:") or " uid:" not in line:
            continue
        name_part, _, uid_part = line.partition(" uid:")
        name = name_part[len("package:") :].strip()
        try:
            validated = validate_package_name(name)
            uid = int(uid_part.strip())
        except (PackageValidationError, ValueError):
            continue
        if uid < 0:
            continue
        existing = uid_packages.get(uid, ())
        if validated not in existing:
            uid_packages[uid] = existing + (validated,)
    return uid_packages