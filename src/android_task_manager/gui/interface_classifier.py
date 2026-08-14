"""Presentation-level classification heuristic for Network panel interfaces.

This exists purely to make the dashboard readable and is explicitly NOT a
guarantee of Android truth. A classified interface (for example ``ccmni3`` →
Mobile Data) is not automatically "the active mobile connection": whether an
interface is actually moving traffic is decided separately from its
throughput, never from its name.

The rule is the first prefix match in order:

* ``wlan*``        → Wi-Fi
* ``ccmni*``       → Mobile Data
* ``rmnet*``       → Mobile Data
* ``ppp*``         → Mobile Data
* ``tun*``/``tap*``→ VPN/Tunnel
* ``p2p*``         → Wi-Fi Direct
* ``lo``           → Loopback
* ``dummy*``/``veth*`` → Virtual
* anything else    → Unknown
"""

from __future__ import annotations

#: Display order for grouped category headers (unknown network types last).
CATEGORY_ORDER = (
    "Mobile Data",
    "Wi-Fi",
    "VPN/Tunnel",
    "Wi-Fi Direct",
    "Loopback",
    "Virtual",
    "Unknown",
)

_MOBILE_PREFIXES = ("ccmni", "rmnet", "ppp")
_WIFI_PREFIXES = ("wlan",)
_VPN_PREFIXES = ("tun", "tap")
_WIFI_DIRECT_PREFIXES = ("p2p",)
_LOOPBACK_NAME = "lo"
_VIRTUAL_PREFIXES = ("dummy", "veth")


def classify_interface(name: str) -> str:
    """Return a human-readable category label for an interface ``name``.

    Order of checks matters: it matches common Android interface names but is
    a display heuristic, not a contract.
    """
    if name == _LOOPBACK_NAME:
        return "Loopback"
    if name.startswith(_MOBILE_PREFIXES):
        return "Mobile Data"
    if name.startswith(_WIFI_PREFIXES):
        return "Wi-Fi"
    if name.startswith(_VPN_PREFIXES):
        return "VPN/Tunnel"
    if name.startswith(_WIFI_DIRECT_PREFIXES):
        return "Wi-Fi Direct"
    if name.startswith(_VIRTUAL_PREFIXES):
        return "Virtual"
    return "Unknown"