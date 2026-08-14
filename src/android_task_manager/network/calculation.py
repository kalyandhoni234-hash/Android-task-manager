"""Throughput calculation from successive network counter samples.

Throughput is always computed from *deltas*: ``(current - previous) / elapsed``.
There is no way to get a rate from a single sample, so every ``calculate_*``
entry point returns ``None`` rates when a baseline is missing (first sample)
or when the elapsed time is not positive.

Counter resets and wraparounds (device reboot, hotplug, driver restarts) are
handled by clamping the delta to zero: throughput is never negative.

Aggregation rule
----------------
The aggregate RX/TX totals and throughput only count *real traffic*
interfaces. Loopback (``lo``) is excluded because it only reflects traffic
already counted on the physical interfaces, and known virtual/tunnel
interfaces (``dummy*``, ``tun*``, ``tap*``, ``p2p*``, ``sit*``, ``wg*``,
``veth*``) are excluded because they would double-count traffic. Everything
else (``wlan*``, ``rmnet*``, ``ccmni*``, ``eth*``, ``ppp*``, …) counts toward
the aggregate. No interface name is hardcoded as "the" traffic interface.
"""

from __future__ import annotations

from .models import (
    NetworkInterfaceSnapshot,
    NetworkSnapshot,
    NetworkThroughput,
)

#: Interface name prefixes that never carry real, user-facing traffic.
_VIRTUAL_PREFIXES = ("dummy", "tun", "tap", "p2p", "sit", "wg", "veth")
_LOOPBACK_NAME = "lo"


def is_traffic_interface(name: str) -> bool:
    """Return True if ``name`` should count toward the aggregate totals.

    Loopback and virtual/tunnel interfaces are excluded so traffic is not
    double-counted; any other interface counts, whatever it is called.
    """
    if name == _LOOPBACK_NAME:
        return False
    return not name.startswith(_VIRTUAL_PREFIXES)


def interface_bytes(interface: NetworkInterfaceSnapshot) -> tuple[int, int]:
    """Return (rx_bytes, tx_bytes) of one interface."""
    return interface.rx_bytes, interface.tx_bytes


def throughput_for(previous_bytes: int, current_bytes: int, elapsed: float) -> float | None:
    """Bytes per second from two counter readings.

    Returns ``None`` when ``elapsed`` is not positive. A negative delta
    (counter reset or wraparound) is clamped to zero, never propagated.
    """
    if elapsed is None or elapsed <= 0:
        return None
    delta = current_bytes - previous_bytes
    if delta < 0:
        delta = 0
    return delta / elapsed


def aggregate_interfaces(interfaces: list[NetworkInterfaceSnapshot]) -> list[NetworkInterfaceSnapshot]:
    """Keep only the real traffic interfaces for aggregate calculations.

    See the module docstring for the documented aggregation rule.
    """
    return [iface for iface in interfaces if is_traffic_interface(iface.name)]


def aggregate_snapshot(interfaces: list[NetworkInterfaceSnapshot]) -> NetworkSnapshot:
    """Build an aggregate view (zero throughput) of a freshly parsed sample."""
    traffic = aggregate_interfaces(interfaces)
    return NetworkSnapshot(
        timestamp=0.0,
        interfaces=list(interfaces),
        aggregate_rx_bytes=sum(i.rx_bytes for i in traffic),
        aggregate_tx_bytes=sum(i.tx_bytes for i in traffic),
        aggregate_rx_packets=sum(i.rx_packets for i in traffic),
        aggregate_tx_packets=sum(i.tx_packets for i in traffic),
        aggregate_rx_errors=sum(i.rx_errors for i in traffic),
        aggregate_tx_errors=sum(i.tx_errors for i in traffic),
        aggregate_rx_drops=sum(i.rx_drops for i in traffic),
        aggregate_tx_drops=sum(i.tx_drops for i in traffic),
    )
