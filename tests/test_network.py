"""Unit tests for network collection: parsing, throughput and aggregation.

No device required. The collector is driven by a fake command runner and the
fixture mirrors the format verified on the Vivo V2026 /proc/net/dev (wlan0
plus ccmni* mobile data and lo).
"""

from __future__ import annotations

import pytest

from android_task_manager.adb.exceptions import ADBDisconnectedError, ADBTimeoutError
from android_task_manager.network.calculation import (
    aggregate_interfaces,
    is_traffic_interface,
    throughput_for,
)
from android_task_manager.network.collector import NetworkCollector
import android_task_manager.network.collector as network_collector
from android_task_manager.network.models import NetworkSnapshot
from android_task_manager.network.parser import NetworkParseError, parse_proc_net_dev

# ---------------------------------------------------------------------------
# Fixtures: two successive /proc/net/dev snapshots (Vivo V2026 layout).
# netA -> netB applies a fixed delta to every interface:
#   wlan0  RX +1_000_000 bytes / 100 packets, TX +100_000 bytes / 50 packets
#   ccmni3 RX +20_000 bytes / 30 packets,      TX +5_000 bytes / 40 packets
#   lo     RX +100 bytes                       TX +100 bytes (excluded)
#   dummy0 RX +400 bytes                       TX +500 bytes (excluded)
# ---------------------------------------------------------------------------

NET_HEADER = (
    "Inter-|   Receive                                                |  Transmit\n"
    " face |bytes    packets errs drop fifo frame compressed multicast|"
    "bytes    packets errs drop fifo colls carrier compressed\n"
)

NET_A = NET_HEADER + (
    " wlan0: 112932964 105705 0 0 0 0 0 0 11157432 31390 577 0 0 0 0 0\n"
    "  ccmni3:  1324567   8129 2 0 0 0 0 0   893241   6115 1 0 0 0 0 0\n"
    "  lo:      18401   2964 0 0 0 0 0 0   18401   2964 0 0 0 0 0 0\n"
    " dummy0:      0      0 0 0 0 0 0 0       0      0 0 0 0 0 0 0\n"
)

NET_B = NET_HEADER + (
    " wlan0: 113932964 105805 0 0 0 0 0 0 11257432 31440 577 0 0 0 0 0\n"
    "  ccmni3:  1344567   8159 2 0 0 0 0 0   898241   6155 1 0 0 0 0 0\n"
    "  lo:      18501   2965 0 0 0 0 0 0   18501   2965 0 0 0 0 0 0\n"
    " dummy0:      400    1 0 0 0 0 0 0       500    1 0 0 0 0 0 0\n"
)


def _interface_names(text: str) -> list[str]:
    return [i.name for i in parse_proc_net_dev(text)]


def _by_name(interfaces: list) -> dict[str, object]:
    return {i.name: i for i in interfaces}


class FakeRunner:
    """Serves successive /proc/net/dev blobs and records commands."""

    def __init__(self, snapshots):
        self._snapshots = list(snapshots)
        self._index = 0
        self.calls: list[list[str]] = []

    def shell(self, args, timeout=None):
        self.calls.append(list(args))
        slot = min(self._index, len(self._snapshots) - 1)
        self._index += 1
        return self._snapshots[slot]


class RaisingRunner:
    """Fails every shell call with a device-level error."""

    def __init__(self, failure) -> None:
        self._failure = failure
        self.calls: list[list[str]] = []

    def shell(self, args, timeout=None):
        self.calls.append(list(args))
        raise self._failure


class SequenceRunner:
    """Serves snapshots then raises, for mid-stream device failure."""

    def __init__(self, snapshots, failure) -> None:
        self._snapshots = list(snapshots)
        self._failure = failure
        self._index = 0

    def shell(self, args, timeout=None):
        if self._index < len(self._snapshots):
            result = self._snapshots[self._index]
            self._index += 1
            return result
        raise self._failure


# ---------------------------------------------------------------------------
# 1-8: Parsing.
# ---------------------------------------------------------------------------


def test_parses_normal_proc_net_dev_layout() -> None:
    interfaces = parse_proc_net_dev(NET_A)
    assert len(interfaces) == 4
    assert _interface_names(NET_A) == ["wlan0", "ccmni3", "lo", "dummy0"]


def test_counter_mapping_extracts_all_four_rx_and_tx_metrics() -> None:
    wlan0 = _by_name(parse_proc_net_dev(NET_A))["wlan0"]
    assert wlan0.rx_bytes == 112932964
    assert wlan0.rx_packets == 105705
    assert wlan0.rx_errors == 0
    assert wlan0.rx_drops == 0
    assert wlan0.tx_bytes == 11157432
    assert wlan0.tx_packets == 31390
    assert wlan0.tx_errors == 577
    assert wlan0.tx_drops == 0


def test_mobile_and_wifi_interface_names_are_kept() -> None:
    names = _interface_names(NET_A)
    assert "ccmni3" in names  # mobile data
    assert "wlan0" in names  # wi-fi
    assert "lo" in names
    assert "dummy0" in names


def test_unusual_interface_names_are_tolerated() -> None:
    text = NET_HEADER + " eth10: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16\n"
    names = _interface_names(text)
    assert names == ["eth10"]


def test_malformed_rows_are_skipped_not_fatal() -> None:
    text = NET_HEADER + (
        " wlan0: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16\n"
        " broken: only a few tokens\n"
        " curept: 1 2 x 4 5 6 7 8 9 10 11 12 13 14 15 16\n"
        " wlan1: 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32\n"
    )
    names = _interface_names(text)
    assert names == ["wlan0", "wlan1"]


def test_whitespace_and_padding_are_tolerated() -> None:
    text = "\n\n" + NET_HEADER + "\n  wlan0: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16\n\n"
    assert _interface_names(text) == ["wlan0"]


def test_trailing_junk_lines_are_ignored() -> None:
    text = NET_HEADER + " wlan0: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16\n" + "garbage\n"
    assert _interface_names(text) == ["wlan0"]


def test_garbage_input_raises_parse_error() -> None:
    with pytest.raises(NetworkParseError):
        parse_proc_net_dev("")
    with pytest.raises(NetworkParseError):
        parse_proc_net_dev("No such file or directory")
    with pytest.raises(NetworkParseError):
        parse_proc_net_dev("unrelated: 1 2 3\n")


def test_empty_but_valid_file_parses_to_empty_list() -> None:
    assert parse_proc_net_dev(NET_HEADER) == []


# ---------------------------------------------------------------------------
# 9-20: Throughput and aggregation.
# ---------------------------------------------------------------------------


def test_throughput_is_delta_over_elapsed() -> None:
    assert throughput_for(100, 400, 2.0) == pytest.approx(150.0, abs=1e-9)
    assert throughput_for(0, 0, 1.0) == 0.0


def test_throughput_elapsed_zero_or_negative_is_unavailable() -> None:
    assert throughput_for(100, 400, 0.0) is None
    assert throughput_for(100, 400, -1.0) is None


def test_throughput_counter_reset_clamps_to_zero() -> None:
    assert throughput_for(1_000_000, 500_000, 5.0) == 0.0
    assert throughput_for(500, 0, 0.5) == 0.0


def test_aggregate_excludes_loopback() -> None:
    interfaces = parse_proc_net_dev(NET_A)
    traffic = aggregate_interfaces(interfaces)
    names = [i.name for i in traffic]
    assert "lo" not in names
    assert "dummy0" not in names
    assert names == ["wlan0", "ccmni3"]


def test_aggregate_tracker_categorizes_network_types() -> None:
    assert is_traffic_interface("wlan0") is True
    assert is_traffic_interface("ccmni5") is True
    assert is_traffic_interface("rmnet_data0") is True
    assert is_traffic_interface("eth0") is True
    assert is_traffic_interface("lo") is False
    assert is_traffic_interface("dummy0") is False
    assert is_traffic_interface("tun0") is False
    assert is_traffic_interface("p2p0") is False
    assert is_traffic_interface("wg0") is False


def test_collector_first_sample_throughput_unavailable() -> None:
    runner = FakeRunner([NET_A])
    snapshot = NetworkCollector(runner).sample()
    assert snapshot.aggregate_throughput.rx_bytes_per_sec is None
    assert snapshot.aggregate_throughput.tx_bytes_per_sec is None
    assert all(
        t.rx_bytes_per_sec is None and t.tx_bytes_per_sec is None
        for t in snapshot.interface_throughput.values()
    )
    assert snapshot.interfaces


def _collector_with_clock(monkeypatch, snapshots) -> tuple[NetworkCollector, FakeRunner]:
    """Drive the collector with a fake monotonic clock at 5.0s per sample."""
    clock = iter([0.0, 5.0])
    monkeypatch.setattr(network_collector.time, "monotonic", lambda: next(clock))
    runner = FakeRunner(snapshots)
    return NetworkCollector(runner), runner


def test_collector_second_sample_reports_aggregate_throughput(monkeypatch) -> None:
    collector, _ = _collector_with_clock(monkeypatch, [NET_A, NET_B])
    collector.sample()
    second = collector.sample()
    assert second.aggregate_rx_bytes == 113932964 + 1344567
    assert second.aggregate_tx_bytes == 11257432 + 898241
    # wlan0 rx +1_000_000, ccmni3 rx +20_000 -> 1_020_000 over 5.0s
    assert second.aggregate_throughput.rx_bytes_per_sec == pytest.approx(1_020_000 / 5.0, abs=1e-9)
    # tx deltas: wlan0 +100_000, ccmni3 +5_000 -> 105_000 over 5.0s
    assert second.aggregate_throughput.tx_bytes_per_sec == pytest.approx(105_000 / 5.0, abs=1e-9)


def test_collector_second_sample_reports_per_interface_throughput(monkeypatch) -> None:
    collector, _ = _collector_with_clock(monkeypatch, [NET_A, NET_B])
    collector.sample()
    second = collector.sample()
    wlan0 = second.interface_throughput["wlan0"]
    assert wlan0.rx_bytes_per_sec == pytest.approx(1_000_000 / 5.0, abs=1e-9)
    assert wlan0.tx_bytes_per_sec == pytest.approx(100_000 / 5.0, abs=1e-9)
    ccmni3 = second.interface_throughput["ccmni3"]
    assert ccmni3.rx_bytes_per_sec == pytest.approx(20_000 / 5.0, abs=1e-9)
    assert ccmni3.tx_bytes_per_sec == pytest.approx(5_000 / 5.0, abs=1e-9)


def test_collector_issues_cat_proc_net_dev_via_runner() -> None:
    runner = FakeRunner([NET_A])
    NetworkCollector(runner).sample()
    assert runner.calls == [["cat", "/proc/net/dev"]]


def test_new_interface_without_previous_baseline_reports_unavailable(monkeypatch) -> None:
    net_first = NET_HEADER + " wlan0: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16\n"
    net_second = NET_HEADER + (
        " wlan0: 101 102 103 104 105 106 107 108 109 110 111 112 113 114 115 116\n"
        " rmnet0: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16\n"
    )
    collector, _ = _collector_with_clock(monkeypatch, [net_first, net_second])
    collector.sample()
    second = collector.sample()
    assert "rmnet0" in second.interface_throughput
    assert second.interface_throughput["rmnet0"].rx_bytes_per_sec is None
    assert second.interface_throughput["rmnet0"].tx_bytes_per_sec is None
    # wlan0 has a baseline: 100 bytes over 5.0s
    assert second.interface_throughput["wlan0"].rx_bytes_per_sec == pytest.approx(20.0, abs=1e-9)


def test_device_disconnected_raises_without_crashing_other_collectors() -> None:
    runner = RaisingRunner(ADBDisconnectedError(detail="bridge reset"))
    collector = NetworkCollector(runner)
    with pytest.raises(ADBDisconnectedError):
        collector.sample()
    assert runner.calls == [["cat", "/proc/net/dev"]]


def test_device_timeout_raises_without_crashing_other_collectors() -> None:
    collector = NetworkCollector(RaisingRunner(ADBTimeoutError(command="cat /proc/net/dev", timeout=10.0)))
    with pytest.raises(ADBTimeoutError):
        collector.sample()


def test_failure_mid_stream_does_not_poison_following_success(monkeypatch) -> None:
    runner = SequenceRunner([NET_A], ADBDisconnectedError(detail="bridge reset"))
    collector = NetworkCollector(runner)
    first = collector.sample()
    assert first.aggregate_throughput.rx_bytes_per_sec is None
    with pytest.raises(ADBDisconnectedError):
        collector.sample()
    # a fresh collector on the same device output works again
    healed, _ = _collector_with_clock(monkeypatch, [NET_A, NET_B])
    healed.sample()
    healed_second = healed.sample()
    assert healed_second.aggregate_throughput.tx_bytes_per_sec == pytest.approx(105_000 / 5.0, abs=1e-9)


def test_aggregate_excludes_unreal_interface_traffic() -> None:
    # Only some of the interfaces in NET_A are real traffic: the aggregate
    # must not include lo or dummy0 bytes, whatever their counters say.
    interfaces = parse_proc_net_dev(NET_A)
    from android_task_manager.network.calculation import aggregate_snapshot

    snapshot = aggregate_snapshot(interfaces)
    assert snapshot.aggregate_rx_bytes == 112932964 + 1324567
    assert snapshot.aggregate_tx_bytes == 11157432 + 893241