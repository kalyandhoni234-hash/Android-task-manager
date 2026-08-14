"""Collector that reads network traffic counters from ``/proc/net/dev``.

The collector is deliberately small: it only drives the ADB command, parses
the output, computes rate deltas against its previous sample and emits a
normalized :class:`~android_task_manager.network.models.NetworkSnapshot`.
All I/O goes through an injectable runner — never ``subprocess`` — so tests
replay scripted output without a device.
"""

from __future__ import annotations

import time

from .calculation import is_traffic_interface, throughput_for
from .models import NetworkInterfaceSnapshot, NetworkSnapshot, NetworkThroughput
from .parser import parse_proc_net_dev


class NetworkCollector:
    """Samples ``/proc/net/dev`` and produces normalized network snapshots.

    The first sample always reports ``None`` throughput (no baseline yet).
    Subsequent samples derive bytes-per-second rates from counter deltas.
    """

    def __init__(self, runner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout
        #: Previous sample state: (per-interface (rx, tx) bytes, traffic-only
        #: aggregate (rx, tx) bytes, monotonic timestamp). ``None`` until the
        #: first sample.
        self._previous: tuple[dict[str, tuple[int, int]], tuple[int, int], float] | None = None

    def sample(self) -> NetworkSnapshot:
        """Read the counters once and produce a fresh snapshot."""
        device_stats = self._runner.shell(["cat", "/proc/net/dev"], timeout=self._timeout)
        interfaces = parse_proc_net_dev(device_stats)
        timestamp = time.monotonic()

        traffic = [i for i in interfaces if is_traffic_interface(i.name)]
        aggregate_rx = sum(i.rx_bytes for i in traffic)
        aggregate_tx = sum(i.tx_bytes for i in traffic)

        interface_throughput: dict[str, NetworkThroughput] = {}
        aggregate_throughput = NetworkThroughput(None, None)

        previous = self._previous
        if previous is not None:
            prev_by_name, (prev_agg_rx, prev_agg_tx), prev_timestamp = previous
            elapsed = timestamp - prev_timestamp
            for interface in interfaces:
                prev_vals = prev_by_name.get(interface.name)
                if prev_vals is None:
                    interface_throughput[interface.name] = NetworkThroughput(None, None)
                    continue
                interface_throughput[interface.name] = NetworkThroughput(
                    rx_bytes_per_sec=throughput_for(prev_vals[0], interface.rx_bytes, elapsed),
                    tx_bytes_per_sec=throughput_for(prev_vals[1], interface.tx_bytes, elapsed),
                )
            aggregate_throughput = NetworkThroughput(
                rx_bytes_per_sec=throughput_for(prev_agg_rx, aggregate_rx, elapsed),
                tx_bytes_per_sec=throughput_for(prev_agg_tx, aggregate_tx, elapsed),
            )

        self._previous = (
            {i.name: (i.rx_bytes, i.tx_bytes) for i in interfaces},
            (aggregate_rx, aggregate_tx),
            timestamp,
        )

        return NetworkSnapshot(
            timestamp=timestamp,
            interfaces=interfaces,
            aggregate_rx_bytes=aggregate_rx,
            aggregate_tx_bytes=aggregate_tx,
            aggregate_rx_packets=sum(i.rx_packets for i in traffic),
            aggregate_tx_packets=sum(i.tx_packets for i in traffic),
            aggregate_rx_errors=sum(i.rx_errors for i in traffic),
            aggregate_tx_errors=sum(i.tx_errors for i in traffic),
            aggregate_rx_drops=sum(i.rx_drops for i in traffic),
            aggregate_tx_drops=sum(i.tx_drops for i in traffic),
            interface_throughput=interface_throughput,
            aggregate_throughput=aggregate_throughput,
        )

    @property
    def previous(self) -> dict[str, tuple[int, int]] | None:
        """The per-interface (rx, tx) bytes of the previous sample, for tests."""
        return None if self._previous is None else self._previous[0]

    def previous_ts(self) -> float | None:
        """The monotonic timestamp of the previous sample, for tests."""
        return None if self._previous is None else self._previous[2]