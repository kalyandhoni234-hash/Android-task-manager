"""Parser for ``/proc/net/dev`` output from an Android device.

The file layout is:

````
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
  wlan0: 112932964 105705 0 0 0 0 0 0 11157432 31390 577 0 0 0 0 0
````

Each data line is ``<name>: <16 counters>`` where the first eight counters are
RX (bytes, packets, errs, drop, fifo, frame, compressed, multicast) and the
second eight are TX (bytes, packets, errs, drop, fifo, colls, carrier,
compressed).

Malformed lines (wrong field count, non-integer counters) are skipped rather
than failing the whole parse: one broken interface must not hide the healthy
ones. Only when the input contains neither a recognizable header nor a single
parseable row is :class:`NetworkParseError` raised, so total garbage (empty
text, an ADB error string) fails loudly while a valid-but-empty interface list
parses to an empty list.
"""

from __future__ import annotations

from .models import NetworkInterfaceSnapshot

#: Recognizable /proc/net/dev header tokens. Used only to accept a
#: valid-but-empty file without raising.
_HEADER_TOKENS = ("face", "bytes", "receive", "transmit")

#: Every data line must carry exactly this many counters.
_COUNTER_COUNT = 16


class NetworkParseError(ValueError):
    """Raised when the input is not recognizably ``/proc/net/dev`` content."""


def parse_proc_net_dev(text: str) -> list[NetworkInterfaceSnapshot]:
    """Parse raw ``/proc/net/dev`` output into normalized snapshots.

    :param text: Raw output of ``cat /proc/net/dev``.
    :return: One snapshot per parsed data line. Line order is preserved.
    :raises NetworkParseError: If the input has neither a header nor a single
        parseable data line.
    """
    interfaces: list[NetworkInterfaceSnapshot] = []
    header_seen = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if any(token in lowered for token in _HEADER_TOKENS) and ":" not in line:
            header_seen = True
            continue
        if ":" not in line:
            continue

        name, _, counters_text = line.partition(":")
        name = name.strip()
        tokens = counters_text.split()
        if len(tokens) < _COUNTER_COUNT:
            continue
        try:
            counters = [int(token) for token in tokens[:_COUNTER_COUNT]]
        except ValueError:
            continue

        interfaces.append(
            NetworkInterfaceSnapshot(
                name=name,
                rx_bytes=counters[0],
                rx_packets=counters[1],
                rx_errors=counters[2],
                rx_drops=counters[3],
                tx_bytes=counters[8],
                tx_packets=counters[9],
                tx_errors=counters[10],
                tx_drops=counters[11],
            )
        )

    if not interfaces and not header_seen:
        raise NetworkParseError("Not /proc/net/dev content: no header or data rows")

    return interfaces