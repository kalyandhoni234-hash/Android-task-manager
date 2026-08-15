"""Unit tests for M14 network investigation: parsing, attribution, collection.

No device required. The socket-table fixtures mirror the byte-exact layout
captured from the Vivo V2026 (Android 11) — including this kernel's extra
trailing columns — so the parser is validated against real device output,
and the UID→package fixtures mirror ``pm list packages -U``.
"""

from __future__ import annotations

import pytest

from android_task_manager.adb.exceptions import ADBDisconnectedError, ADBTimeoutError
from android_task_manager.network_investigation.collector import (
    NetworkInvestigationCollector,
    _SOCKET_TABLES,
)
from android_task_manager.network_investigation.models import (
    NetworkInvestigationSnapshot,
    SocketInfo,
)
from android_task_manager.network_investigation.parser import (
    SocketTableParseError,
    parse_socket_table,
    parse_uid_packages,
)

# ---------------------------------------------------------------------------
# Fixtures — byte-exact rows captured from the Vivo V2026.
# ---------------------------------------------------------------------------

TCP4_HEADER = (
    "sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt"
    " uid timeout inode\n"
)
# 100.86.5.166:50418 -> 38.134.100.98:443, FIN-WAIT-1, plus this kernel's
# trailing extra columns.
TCP4_ROW = (
    "  0: A6055664:C4F2 62648626:01BB 04 00000001:00000000 00:00000000"
    " 00000000     0        0 0 1 0000000000000000 72 4 30 10 -1\n"
)

TCP6_HEADER = (
    "sl local_address                         remote_address"
    "                        st tx_queue rx_queue tr tm->when retrnsmt"
    " uid timeout inode\n"
)
# system (UID 1000) LISTEN socket: 2402:8100:...:13C4 on :5050.
TCP6_LISTEN = (
    "  0: 00810224CE44469F01F499134D004B64:13C4"
    " 00000000000000000000000000000000:0000 0A 00000000:00000000"
    " 00:00000000 00000000  1000        0 30441146 1 0000000000000000"
    " 100 0 0 10 0\n"
)
# Instagram (UID 10203) CLOSE-WAIT socket, NAT64 destination.
TCP6_INSTAGRAM = (
    "  7: 008102242828E139EBE8095A40AB1FEC:B3B6"
    " 9BFF640000000000000000002711F09D:01BB 08 00000000:00000019"
    " 00:00000000 00000000 10203        0 30828972 1 0000000000000000"
    " 47 4 28 10 -1\n"
)
# v4-mapped row on the tcp6 table: 192.168.0.185:35282 -> 35.60.75.83:443.
TCP6_V4MAPPED = (
    " 11: 0000000000000000FFFF0000B900A8C0:89D2"
    " 0000000000000000FFFF0000533CAD23:01BB 04 00000001:00000000"
    " 00:00000000 00000002     0        0 0 1 0000000000000000"
    " 361 4 8 1 5\n"
)

UDP4_HEADER = (
    "sl local_address rem_address   st tx_queue rx_queue tr tm->when"
    " retrnsmt   uid  timeout inode ref pointer drops\n"
)
# Instagram (UID 10203) UDP bind on :0xE801 (59393) — no TCP state.
UDP4_BIND = (
    "1058: 00000000:E801 00000000:0000 07 00000000:00000000 00:00000000"
    " 00000000     10203        0 30557648 2 0000000000000000 0\n"
)

PM_LIST = (
    "package:com.google.android.youtube uid:10181\n"
    "package:com.instagram.android uid:10203\n"
    "package:com.mediatek.gba uid:1001\n"
    "package:com.mediatek.ims uid:1001\n"
    "package:com.android.cts.priv.ctsshim uid:10198\n"
)


# ---------------------------------------------------------------------------
# 1-10: Socket-table parsing.
# ---------------------------------------------------------------------------


def test_parses_tcp4_row_with_kernel_extra_columns() -> None:
    sockets = parse_socket_table(TCP4_HEADER + TCP4_ROW, "tcp", "ipv4")
    assert len(sockets) == 1
    socket = sockets[0]
    assert socket.protocol == "tcp"
    assert socket.family == "ipv4"
    assert socket.local_address == "100.86.5.166"
    assert socket.local_port == 50418
    assert socket.remote_address == "38.134.100.98"
    assert socket.remote_port == 443
    assert socket.state == "FIN-WAIT-1"
    assert socket.uid == 0
    assert socket.inode == 0


def test_parses_tcp6_listen_socket() -> None:
    sockets = parse_socket_table(TCP6_HEADER + TCP6_LISTEN, "tcp", "ipv6")
    assert len(sockets) == 1
    socket = sockets[0]
    assert socket.family == "ipv6"
    assert socket.local_address.startswith("2402:8100:")
    assert socket.local_port == 0x13C4
    assert socket.remote_address == "0000:0000:0000:0000:0000:0000:0000:0000"
    assert socket.remote_port == 0
    assert socket.state == "LISTEN"
    assert socket.uid == 1000
    assert socket.inode == 30441146


def test_parses_tcp6_socket_with_real_app_uid() -> None:
    sockets = parse_socket_table(TCP6_HEADER + TCP6_INSTAGRAM, "tcp", "ipv6")
    assert len(sockets) == 1
    socket = sockets[0]
    assert socket.uid == 10203
    assert socket.state == "CLOSE-WAIT"
    assert socket.remote_address.startswith("0064:ff9b:")  # NAT64 64:ff9b::
    assert socket.remote_port == 443


def test_v4_mapped_rows_are_attributed_as_ipv4() -> None:
    sockets = parse_socket_table(TCP6_HEADER + TCP6_V4MAPPED, "tcp", "ipv6")
    assert len(sockets) == 1
    socket = sockets[0]
    assert socket.family == "ipv4"
    assert socket.local_address == "192.168.0.185"
    assert socket.local_port == 0x89D2
    assert socket.remote_address == "35.173.60.83"
    assert socket.remote_port == 443


def test_udp_rows_carry_no_tcp_state() -> None:
    sockets = parse_socket_table(UDP4_HEADER + UDP4_BIND, "udp", "ipv4")
    assert len(sockets) == 1
    socket = sockets[0]
    assert socket.state is None
    assert socket.uid == 10203
    assert socket.local_address == "0.0.0.0"
    # A real kernel value of 0.0.0.0:0 stays honest rather than "N/A".
    assert socket.remote_address == "0.0.0.0"
    assert socket.remote_port == 0


def test_unknown_tcp_state_is_kept_raw_never_fabricated() -> None:
    text = TCP4_HEADER + (
        "  0: 00000000:1F90 00000000:0000 0C 00000000:00000000"
        " 00:00000000 00000000  10203        0 12345 1 0000000000000000 0\n"
    )
    sockets = parse_socket_table(text, "tcp", "ipv4")
    assert sockets[0].state == "0C"


def test_malformed_rows_are_skipped_not_fatal() -> None:
    text = TCP4_HEADER + (
        "  0: 00000000:1F90 00000000:0000 0A 00000000:00000000"
        " 00:00000000 00000000  1000        0 1001 1 0000000000000000 0\n"
        "  BADROWJUNK not:an address 0A more:garbage here\n"
        "  2: NOTHEX:1F90 00000000:0000 0A 00000000:00000000"
        " 00:00000000 00000000  1000        0 1002 1 0000000000000000 0\n"
    )
    sockets = parse_socket_table(text, "tcp", "ipv4")
    assert len(sockets) == 1
    assert sockets[0].inode == 1001


def test_negative_or_typed_columns_skip_row() -> None:
    text = TCP4_HEADER + (
        "  5: 00000000:1F91 00000000:0000 0A 00000000:00000000"
        " 00:00000000 00000000  -1000        0 1003 1 0000000000000000 0\n"
        "  6: 00000000:1F92 00000000:0000 0A 00000000:00000000"
        " 00:00000000 00000000  abcde        0 1004 1 0000000000000000 0\n"
    )
    assert parse_socket_table(text, "tcp", "ipv4") == []


def test_multiple_tcp4_rows_preserve_order() -> None:
    repeated = TCP4_HEADER + TCP4_ROW + TCP4_ROW
    sockets = parse_socket_table(repeated, "tcp", "ipv4")
    assert [s.inode for s in sockets] == [0, 0]


def test_garbage_input_raises_parse_error() -> None:
    with pytest.raises(SocketTableParseError):
        parse_socket_table("", "tcp", "ipv4")
    with pytest.raises(SocketTableParseError):
        parse_socket_table("No such file or directory", "tcp", "ipv4")
    with pytest.raises(SocketTableParseError):
        parse_socket_table("Permission denied", "tcp", "ipv4")


def test_empty_table_with_header_parses_to_empty_list() -> None:
    assert parse_socket_table(TCP6_HEADER, "tcp", "ipv6") == []


def test_junk_after_header_is_ignored() -> None:
    text = TCP4_HEADER + TCP4_ROW + "garbage\n" + "more junk\n"
    assert len(parse_socket_table(text, "tcp", "ipv4")) == 1


# ---------------------------------------------------------------------------
# 11-14: UID -> package attribution.
# ---------------------------------------------------------------------------


def test_packages_shared_uid_are_all_kept() -> None:
    uid_packages = parse_uid_packages(PM_LIST)
    assert uid_packages[1001] == ("com.mediatek.gba", "com.mediatek.ims")
    assert uid_packages[10181] == ("com.google.android.youtube",)
    assert uid_packages[10203] == ("com.instagram.android",)


def test_junk_pm_lines_are_skipped() -> None:
    text = (
        "package:com.instagram.android uid:10203\n"
        "package:not a valid name uid:1\n"
        "package:shell uid xyz\n"
        "package:bad;rm uid:2\n"
        "total packages: 999\n"
    )
    assert parse_uid_packages(text) == {10203: ("com.instagram.android",)}


def test_snapshot_attribution_helpers() -> None:
    sockets = parse_socket_table(
        TCP6_HEADER + TCP6_LISTEN + TCP6_INSTAGRAM, "tcp", "ipv6"
    )
    snapshot = NetworkInvestigationSnapshot(
        timestamp=1.0,
        sockets=tuple(sockets),
        source_available=True,
        uid_packages={10203: ("com.instagram.android",)},
    )
    attributed = snapshot.sockets_for_uid(10203)
    assert len(attributed) == 1
    assert attributed[0] is sockets[1]
    assert snapshot.packages_for_uid(10203) == ("com.instagram.android",)
    assert snapshot.packages_for_uid(999999) == ()


# ---------------------------------------------------------------------------
# 15-22: Collector behavior (fake runner, real device data shapes).
# ---------------------------------------------------------------------------


class FakeRunner:
    """Serves canned output per command line; records calls.

    Any command without canned output serves a header-only table so the
    collector never sees unexpected data in these tests.
    """

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self._responses = dict(responses or {})
        self.calls: list[list[str]] = []
        self.failures: dict[str, BaseException] = {}

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        key = " ".join(args)
        if key in self.failures:
            raise self.failures[key]
        if key not in self._responses:
            if key.startswith("cat /proc/net/"):
                return (
                    TCP4_HEADER
                    if key.endswith("/tcp")
                    else TCP6_HEADER
                    if key.endswith("tcp6")
                    else UDP4_HEADER
                )
            return ""
        return self._responses[key]


class RaisingRunner(FakeRunner):
    """Fails every call with the given device-level error."""

    def __init__(self, failure, responses: dict[str, str] | None = None) -> None:
        super().__init__(responses)
        self._failure = failure

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        raise self._failure


def test_collector_reads_all_four_tables_and_pm_in_one_pass() -> None:
    runner = FakeRunner(
        {
            "cat /proc/net/tcp": TCP4_HEADER + TCP4_ROW,
            "cat /proc/net/tcp6": TCP6_HEADER + TCP6_INSTAGRAM + TCP6_V4MAPPED,
            "cat /proc/net/udp": UDP4_HEADER + UDP4_BIND,
            "cat /proc/net/udp6": UDP6_HEADER(),
            "pm list packages -U": PM_LIST,
        }
    )
    snapshot = NetworkInvestigationCollector(runner).sample()
    assert [c for c in runner.calls] == [
        ["cat", "/proc/net/tcp"],
        ["cat", "/proc/net/tcp6"],
        ["cat", "/proc/net/udp"],
        ["cat", "/proc/net/udp6"],
        ["pm", "list", "packages", "-U"],
    ]
    assert snapshot.source_available is True
    assert snapshot.source_errors == ()
    assert len(snapshot.sockets) == 4  # 1 tcp4 + 2 tcp6 + 1 udp
    assert snapshot.packages_for_uid(10203) == ("com.instagram.android",)
    assert snapshot.sockets_for_uid(10203)  # the CLOSE-WAIT + UDP bind


def test_collector_source_available_with_partial_table_failure() -> None:
    runner = FakeRunner(
        {
            "cat /proc/net/tcp": TCP4_HEADER + TCP4_ROW,
            "cat /proc/net/tcp6": "Permission denied",
        }
    )
    snapshot = NetworkInvestigationCollector(runner).sample()
    assert snapshot.source_available is True
    assert any("tcp6" in error for error in snapshot.source_errors)
    assert len(snapshot.sockets) == 1


def test_collector_source_unavailable_when_all_tables_garbage() -> None:
    runner = FakeRunner(
        {
            "cat /proc/net/tcp": "Permission denied",
            "cat /proc/net/tcp6": "Permission denied",
            "cat /proc/net/udp": "Permission denied",
            "cat /proc/net/udp6": "Permission denied",
        }
    )
    snapshot = NetworkInvestigationCollector(runner).sample()
    assert snapshot.source_available is False
    assert len(snapshot.sockets) == 0
    assert len(snapshot.source_errors) == 4


def test_collector_pm_failure_keeps_sockets_but_no_packages() -> None:
    runner = FakeRunner(
        {
            "cat /proc/net/tcp": TCP4_HEADER + TCP4_ROW,
            "pm list packages -U": "Permission denied",
        }
    )
    snapshot = NetworkInvestigationCollector(runner).sample()
    assert len(snapshot.sockets) == 1
    assert snapshot.uid_packages == {}
    # "Permission denied" as stdout is legal-but-empty output for pm; the
    # attribution map is simply empty. A real command failure records an error.


def test_collector_pm_command_failure_records_source_error() -> None:
    from android_task_manager.adb.exceptions import ADBCommandError

    runner = FakeRunner(
        {
            "cat /proc/net/tcp": TCP4_HEADER + TCP4_ROW,
        }
    )
    runner.failures = {
        "pm list packages -U": ADBCommandError("shell pm list packages -U", 1)
    }
    snapshot = NetworkInvestigationCollector(runner).sample()
    assert len(snapshot.sockets) == 1
    assert snapshot.uid_packages == {}
    assert any("pm list" in error for error in snapshot.source_errors)


def test_collector_device_disconnected_raises() -> None:
    runner = RaisingRunner(ADBDisconnectedError(detail="bridge reset"))
    collector = NetworkInvestigationCollector(runner)
    with pytest.raises(ADBDisconnectedError):
        collector.sample()
    assert len(runner.calls) == 1


def test_collector_timeout_raises() -> None:
    collector = NetworkInvestigationCollector(
        RaisingRunner(ADBTimeoutError(command="cat /proc/net/tcp", timeout=10.0))
    )
    with pytest.raises(ADBTimeoutError):
        collector.sample()


def test_collector_snapshot_is_bounded_and_replaced() -> None:
    """Each pass builds a fresh snapshot; growing history must not leak in."""
    runner = FakeRunner(
        {
            "cat /proc/net/tcp": TCP4_HEADER + TCP4_ROW,
            "cat /proc/net/tcp6": TCP6_HEADER + TCP6_LISTEN,
            "cat /proc/net/udp": UDP4_HEADER + UDP4_BIND,
            "cat /proc/net/udp6": UDP6_HEADER(),
            "pm list packages -U": PM_LIST,
        }
    )
    collector = NetworkInvestigationCollector(runner)
    first = collector.sample()
    second = collector.sample()
    assert first is not second
    assert second.timestamp >= first.timestamp
    assert len(second.sockets) == 3


def test_collector_table_manifest_is_stable() -> None:
    assert [(p, proto, family) for p, proto, family in _SOCKET_TABLES] == [
        ("/proc/net/tcp", "tcp", "ipv4"),
        ("/proc/net/tcp6", "tcp", "ipv6"),
        ("/proc/net/udp", "udp", "ipv4"),
        ("/proc/net/udp6", "udp", "ipv6"),
    ]


def UDP6_HEADER() -> str:
    return (
        "sl local_address                         remote_address"
        "                        st tx_queue rx_queue tr tm->when retrnsmt"
        " uid timeout inode ref pointer drops\n"
    )