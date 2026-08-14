"""Normalized network data models.

The ``NetworkSnapshot`` is the contract between the network parser, collector,
calculation, terminal renderer and GUI. Raw ``/proc/net/dev`` output never
reaches the presentation layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NetworkInterfaceSnapshot:
    """Counter snapshot for one discovered network interface.

    Counter layout follows ``/proc/net/dev``: the first four RX columns are
    bytes/packets/errors/drops and the first four TX columns are the same.
    """

    name: str
    rx_bytes: int
    tx_bytes: int
    rx_packets: int
    tx_packets: int
    rx_errors: int
    tx_errors: int
    rx_drops: int
    tx_drops: int


@dataclass(frozen=True)
class NetworkThroughput:
    """Computed transfer rates, in bytes/second, for one thing.

    ``None`` means "not available yet" — always true on the first sample and on
    any sample with zero/negative elapsed time. Values are never negative.
    """

    rx_bytes_per_sec: float | None
    tx_bytes_per_sec: float | None


@dataclass(frozen=True)
class NetworkSnapshot:
    """A normalized view of the device's network interfaces at one moment.

    ``interfaces`` keeps every discovered interface (including loopback and
    virtual ones) for future detailed views. The ``aggregate_*`` fields and
    ``aggregate_throughput`` are totals over real traffic interfaces only —
    see :func:`~android_task_manager.network.calculation.aggregate_interfaces`
    for the documented rule.
    """

    #: Monotonic timestamp of the sample.
    timestamp: float
    #: Every discovered interface (loopback and virtual included).
    interfaces: list[NetworkInterfaceSnapshot] = field(default_factory=list)

    #: Aggregate RX/TX counters over real traffic interfaces.
    aggregate_rx_bytes: int = 0
    aggregate_tx_bytes: int = 0
    aggregate_rx_packets: int = 0
    aggregate_tx_packets: int = 0
    aggregate_rx_errors: int = 0
    aggregate_tx_errors: int = 0
    aggregate_rx_drops: int = 0
    aggregate_tx_drops: int = 0

    #: Per-interface throughput this sample (None until a baseline exists).
    interface_throughput: dict[str, NetworkThroughput] = field(default_factory=dict)
    #: Aggregate throughput over real traffic interfaces.
    aggregate_throughput: NetworkThroughput = field(
        default_factory=lambda: NetworkThroughput(None, None)
    )