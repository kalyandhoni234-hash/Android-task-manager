"""Parsers for raw device-information command output.

Each parser is a pure function: raw text in, structured value out. Every
parser tolerates malformed or unexpected output by returning ``None``
rather than raising — a bad value on one property must never break the
rest of the device page.
"""

from __future__ import annotations

import dataclasses
import ipaddress
import re
from datetime import date, datetime, timezone

from .models import NetworkInterfaceInfo, StorageInfo

#: The address Android reports when a MAC is not available (privacy
#: placeholder since Android 6): a real 12-hex-digit address, all zeros.
_MAC_PLACEHOLDER = "02:00:00:00:00:00"
_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def parse_getprop_output(text: str) -> dict[str, str]:
    """Parse the bulk ``getprop`` output (``[key]: [value]`` per line).

    Lines that do not follow the bracket format are ignored. A key present
    with an empty value is kept as ``""`` so callers can distinguish
    "explicitly empty" from "absent".
    """
    props: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("[") or line.find("]: [") < 0:
            continue
        key_end = line.find("]: [")
        key = line[1:key_end]
        value = line[key_end + 4 :]
        if value.endswith("]"):
            value = value[:-1]
        props[key] = value
    return props


def parse_wm_size(text: str) -> str | None:
    """Extract the physical screen size from ``wm size`` output.

    ``wm`` reports both physical and (when set) override sizes; only the
    physical size describes the actual panel, so it wins.
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Physical size:"):
            value = line[len("Physical size:") :].strip()
            return value or None
    return None


def parse_wm_density(text: str) -> int | None:
    """Extract the physical density in dpi from ``wm density`` output."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Physical density:"):
            value = line[len("Physical density:") :].strip()
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _parse_dimensions(value: str) -> tuple[int, int] | None:
    """``"WxH"`` with two positive integers -> (W, H), else None."""
    if not value or "x" not in value:
        return None
    parts = value.split("x")
    if len(parts) != 2:
        return None
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def parse_wm_size_dimensions(text: str) -> tuple[int, int] | None:
    """Physical screen size as (width, height) pixels from ``wm size``.

    The physical size describes the actual panel and wins over an override,
    mirroring ``parse_wm_size``. Dimensions must be positive integers;
    anything else -> None.
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Physical size:"):
            return _parse_dimensions(line[len("Physical size:") :].strip())
    return None


def parse_wm_override_size(text: str) -> str | None:
    """The ``wm size`` override ("WxH") when one is set; else None.

    Android prints ``Override size: null`` when no override is configured;
    only a well-formed ``WxH`` value is reported.
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Override size:"):
            value = line[len("Override size:") :].strip()
            if value.lower() == "null":
                return None
            return value if _parse_dimensions(value) is not None else None
    return None


def parse_wm_override_density(text: str) -> int | None:
    """The ``wm density`` override in dpi when one is set; else None.

    ``Override density: null`` (no override configured) and non-positive or
    malformed values -> None.
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Override density:"):
            value = line[len("Override density:") :].strip()
            if value.lower() == "null":
                return None
            try:
                parsed = int(value)
            except ValueError:
                return None
            return parsed if parsed > 0 else None
    return None


def parse_df_k(text: str) -> list[StorageInfo]:
    """Parse ``df -k`` output into volumes.

    Header lines and unparseable rows are skipped. The first column is the
    filesystem, the last column (or columns) the mount point; malformed
    numeric cells mark that row unavailable rather than aborting the parse.
    """
    volumes: list[StorageInfo] = []
    for raw in text.splitlines():
        parts = raw.split()
        if not parts or len(parts) < 5:
            continue
        if parts[0] in ("Filesystem", "Filesystem 1K-blocks"):
            continue
        try:
            total_kb = int(parts[1])
            used_kb = int(parts[2])
            available_kb = int(parts[3])
        except ValueError:
            continue
        mount = " ".join(parts[5:]).strip() or parts[4]
        volumes.append(
            StorageInfo(
                mount=mount,
                total_kb=total_kb,
                used_kb=used_kb,
                available_kb=available_kb,
            )
        )
    return volumes


def pick_internal_storage(volumes: list[StorageInfo]) -> StorageInfo | None:
    """The internal shared-storage volume: ``/data`` exactly, else None.

    On file-based-encryption devices ``df -k /data`` resolves to the
    current user's view of the same filesystem (``/data/user/0``); that
    mount is accepted as well. Only the device's internal storage is
    reported; other volumes are never silently combined into it.
    """
    for preferred in ("/data", "/data/user/0"):
        for volume in volumes:
            if volume.mount == preferred:
                return volume
    return None


_REFRESH_RATE_PATTERNS = (
    re.compile(r"mRefreshRate=\s*([0-9.]+)"),
    re.compile(r"mDefaultRefreshRate=\s*([0-9.]+)"),
    re.compile(r"refreshRate[\s=:]+([0-9.]+)"),
)


def parse_refresh_rate(text: str) -> float | None:
    """Best-effort display refresh rate in Hz from ``dumpsys display``.

    Token names differ across Android versions; each pattern is tried in
    order until one matches.
    """
    for pattern in _REFRESH_RATE_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def parse_supported_refresh_rates(text: str) -> tuple[float, ...] | None:
    """Distinct refresh rates (Hz) advertised by ``dumpsys display``.

    Display-mode entries carry a ``refreshRate=<Hz>`` token; every distinct
    positive value is collected (non-numeric, zero and negative tokens are
    ignored) and returned sorted ascending. No usable token -> None.
    """
    rates: set[float] = set()
    for match in re.finditer(r"refreshRate=([0-9.]+)", text):
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        if value > 0:
            rates.add(value)
    return tuple(sorted(rates)) or None


def parse_orientation(text: str) -> str | None:
    """Surface orientation from ``dumpsys input`` (SurfaceOrientation: N)."""
    match = re.search(r"SurfaceOrientation:\s*([0-3])", text)
    if match is None:
        return None
    return {
        "0": "Portrait",
        "1": "Landscape",
        "2": "Reverse portrait",
        "3": "Reverse landscape",
    }.get(match.group(1))


def parse_orientation_degrees(text: str) -> int | None:
    """Surface orientation in degrees (0/90/180/270) from ``dumpsys input``.

    ``SurfaceOrientation`` is a value 0-3 meaning 0/90/180/270 degrees of
    rotation; values outside that range are malformed -> None.
    """
    match = re.search(r"SurfaceOrientation:\s*([0-3])", text)
    if match is None:
        return None
    return {"0": 0, "1": 90, "2": 180, "3": 270}.get(match.group(1))


# ---------------------------------------------------------------------------
# GPU facts
# ---------------------------------------------------------------------------


def parse_gpu_gles(text: str) -> tuple[str | None, str | None]:
    """GPU vendor/model from the ``dumpsys SurfaceFlinger`` GLES line.

    The line reads ``GLES: <vendor>, <renderer>`` (e.g. "GLES: Qualcomm,
    Adreno (TM) 610"). The first GLES line wins. A renderer without a
    vendor prefix yields ``(None, renderer)``; an empty value yields
    ``(None, None)``.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("GLES:"):
            continue
        rest = line[len("GLES:") :].strip()
        if not rest:
            return (None, None)
        if "," in rest:
            vendor, renderer = rest.split(",", 1)
            return vendor.strip() or None, renderer.strip() or None
        return None, rest
    return (None, None)


# ---------------------------------------------------------------------------
# Battery static facts / storage filesystem
# ---------------------------------------------------------------------------


def parse_charge_full_design(text: str) -> int | None:
    """Design capacity (``charge_full_design``); positive int, else None.

    The value is kept verbatim — the kernel convention is microamp-hours
    but OEMs vary, so no unit conversion is claimed. Zero, negative and
    malformed values -> None: a capacity of zero is not meaningful.
    """
    value = text.strip()
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def parse_cycle_count(text: str) -> int | None:
    """Battery charge cycle count; non-negative int, else None.

    Zero is a real value (a new battery), so it is preserved; only
    negative or malformed values are rejected.
    """
    value = text.strip()
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def parse_mounts_filesystem(text: str, mounts: tuple[str, ...]) -> str | None:
    """Filesystem type of the first matching mount in ``/proc/mounts``.

    Each line is ``device mountpoint type options dump pass``; the kernel
    escapes spaces in paths, so whitespace splitting is safe. The first
    line whose mount point is in ``mounts`` wins; no match -> None.
    """
    for raw in text.splitlines():
        parts = raw.split()
        if len(parts) < 3:
            continue
        if parts[1] in mounts:
            value = parts[2].strip()
            return value or None
    return None


def parse_mac_address(text: str) -> str | None:
    """A real MAC address, or None (placeholder/malformed values excluded).

    Android substitutes ``02:00:00:00:00:00`` when the real address is not
    available; reporting that placeholder as a fact would be dishonest.
    """
    value = text.strip()
    if not value or value.lower() == _MAC_PLACEHOLDER:
        return None
    if _MAC_RE.match(value) is None:
        return None
    return value.lower()


def parse_android_id(text: str) -> str | None:
    """The ``settings get secure android_id`` value; ``null``/empty -> None."""
    value = text.strip()
    if not value or value.lower() == "null":
        return None
    return value


def parse_cpu_hardware_line(text: str) -> str | None:
    """The ``Hardware`` line of /proc/cpuinfo ("" or absent -> None)."""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Hardware") and ":" in line:
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def parse_max_frequency_khz(text: str) -> int | None:
    """An integer kHz value from a cpufreq node (malformed -> None)."""
    value = text.strip()
    try:
        return int(value)
    except ValueError:
        return None


def _empty_to_none(value: str | None) -> str | None:
    """Normalize a raw property value: empty string -> None."""
    if value is None or not value.strip():
        return None
    return value.strip()


# ---------------------------------------------------------------------------
# Kernel, uptime and boot-time facts
# ---------------------------------------------------------------------------


def parse_uname_a(text: str) -> str | None:
    """The full kernel version line from ``uname -a`` (empty -> None).

    The complete line carries the kernel release, build number, build date
    and architecture; a multi-line response keeps only the first line.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            return line
    return None


def parse_proc_uptime(text: str) -> float | None:
    """Uptime in seconds: the first token of ``/proc/uptime``.

    The file reports ``<uptime> <idle>`` as fractional seconds; the idle
    token is ignored and negative/absent/malformed values become ``None``.
    """
    parts = text.strip().split()
    if not parts:
        return None
    try:
        value = float(parts[0])
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def parse_epoch_seconds(text: str) -> int | None:
    """An epoch-seconds value from ``date +%s`` (malformed -> None)."""
    value = text.strip()
    try:
        return int(value)
    except ValueError:
        return None


def derive_boot_time(device_epoch: int, uptime_seconds: float) -> datetime | None:
    """Boot time (UTC) derived as ``device clock − uptime``.

    This is an estimate, never an authoritative value: it inherits the
    device clock's accuracy and any clock drift. The derivation is only
    produced when it is reliable — the uptime must be non-negative and the
    device clock must not be behind the uptime — and is otherwise ``None``.
    """
    if uptime_seconds < 0 or device_epoch < uptime_seconds:
        return None
    return datetime.fromtimestamp(device_epoch - uptime_seconds, tz=timezone.utc)


# ---------------------------------------------------------------------------
# CPU architecture, topology and frequency facts
# ---------------------------------------------------------------------------


def parse_uname_a_machine(text: str) -> str | None:
    """The machine token of ``uname -a`` (always the last token).

    ``uname -a`` is ``kernel hostname release <version...> machine``; the
    version portion may contain spaces, so only the trailing token is
    reliable. Empty/malformed input -> None.
    """
    parts = text.strip().split()
    return parts[-1] if parts else None


#: Documented mapping from uname machine token to 64-bit capability.
#: Tokens not listed (e.g. "armv8l", a 64-bit-capable core running a 32-bit
#: kernel/userspace) yield None rather than a guess.
_CPU_64BIT_MACHINES = frozenset({"aarch64", "arm64", "x86_64", "amd64"})
_CPU_32BIT_MACHINES = frozenset(
    {"armv7l", "armv6l", "armv5tejl", "i686", "i586", "i386"}
)


def derive_cpu_64bit(machine: str | None) -> bool | None:
    """64-bit capability from a uname machine token; ambiguous -> None."""
    if machine is None:
        return None
    if machine in _CPU_64BIT_MACHINES:
        return True
    if machine in _CPU_32BIT_MACHINES:
        return False
    return None


def parse_cpu_range(text: str) -> int | None:
    """Number of CPUs covered by a sysfs cpu-range file (online/present).

    Handles ``"0-7"``, a bare ``"4"`` and comma lists such as
    ``"0-3,8-11"``. Malformed, inverted or empty ranges -> None; a zero
    total (no CPUs) is treated as invalid and returns None.
    """
    total = 0
    for segment in text.strip().split(","):
        segment = segment.strip()
        if not segment:
            return None
        if "-" in segment:
            bounds = segment.split("-")
            if len(bounds) != 2:
                return None
            try:
                start = int(bounds[0].strip())
                end = int(bounds[1].strip())
            except ValueError:
                return None
            if end < start:
                return None
            total += end - start + 1
        else:
            try:
                value = int(segment)
            except ValueError:
                return None
            if value < 0:
                return None
            total += 1
    return total or None


def parse_cpuinfo_cores(text: str) -> int | None:
    """Logical core count from /proc/cpuinfo (``processor`` entries)."""
    count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("processor") and ":" in line:
            count += 1
    return count or None


def parse_cpufreq_khz(text: str) -> int | None:
    """A cpufreq value in kHz (zero allowed; negative/malformed -> None).

    Zero is a real kernel-reported value (e.g. a sleeping core), so it is
    preserved; only negative or non-numeric values are rejected.
    """
    value = text.strip()
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


#: Canonical frequency unit for the CPU frequency model fields.
_Hz_PER_KHZ = 1000.0


def khz_to_hz(khz: int) -> float:
    """Convert a kHz value to the canonical Hz unit (kHz * 1000)."""
    return khz * _Hz_PER_KHZ


def parse_governor(text: str) -> str | None:
    """The CPU scaling governor name (empty/whitespace -> None)."""
    value = text.strip()
    return value or None


#: ARM reports features on a ``Features`` line, x86 on a ``flags`` line.
_CPU_FEATURE_LINE_KEYS = ("Features", "flags")


def parse_cpu_features(text: str) -> tuple[str, ...] | None:
    """Normalized CPU feature names from /proc/cpuinfo.

    The first matching line (ARM ``Features:`` or x86 ``flags:``) is split,
    lowercased and de-duplicated while preserving source order. No line,
    an empty value, or an unrecognized key -> None.
    """
    for raw in text.splitlines():
        line = raw.strip()
        for key in _CPU_FEATURE_LINE_KEYS:
            if line.startswith(key) and ":" in line:
                tokens = line.split(":", 1)[1].split()
                features: list[str] = []
                for token in tokens:
                    normalized = token.lower()
                    if normalized not in features:
                        features.append(normalized)
                return tuple(features) or None
    return None


def parse_cpuinfo_model_name(text: str) -> str | None:
    """The ``model name`` line of /proc/cpuinfo (empty/absent -> None)."""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("model name") and ":" in line:
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


# ---------------------------------------------------------------------------
# Network configuration: ip addr / ip route
# ---------------------------------------------------------------------------
# SNAPSHOT data: interface identity, type, MAC, addresses, prefixes and the
# default route are read once per connection session. Live traffic counters
# and throughput are owned by the network monitor package — never here.

#: Interface header: ``2: wlan0: <FLAGS> mtu ...``. The name token follows the
#: index and colon; flags are inside the angle brackets. ``UP`` in the flags
#: is the universal up indicator (the ``state`` token is newer and absent on
#: some builds, so it is never required).
_INTERFACE_HEADER_RE = re.compile(r"^\s*\d+:\s+(\S+):\s+<(.*?)>")
#: Address line: ``inet 192.168.50.10/24 brd ...`` / ``inet6 fe80::/64 scope``.
_INET_RE = re.compile(r"^\s*inet\s+(\S+)")
_INET6_RE = re.compile(r"^\s*inet6\s+(\S+)")
#: MAC line: ``link/ether 3c:28:6d:ab:cd:ef brd ...`` (loopback is
#: ``link/loopback 00:00:00:00:00:00``).
_LINK_RE = re.compile(r"^\s*link/\S+\s+([0-9A-Fa-f:]+)")

#: Documented interface-type classification (fallback when the link layer
#: does not decide). Only well-known prefixes are mapped; anything else is
#: honestly reported as "Other" instead of being guessed.
_INTERFACE_TYPE_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("wlan", "Wi-Fi"),
    ("wifi", "Wi-Fi"),
    ("rmnet", "Cellular"),
    ("ccmni", "Cellular"),
    ("pdp", "Cellular"),
    ("wwan", "Cellular"),
    ("eth", "Ethernet"),
    ("en", "Ethernet"),
    ("tun", "VPN"),
    ("tap", "VPN"),
    ("ppp", "VPN"),
    ("wg", "VPN"),
)


def _classify_interface(name: str, link_type: str) -> str:
    """Interface type: link layer first, documented name mapping as fallback.

    ``link/loopback`` decides Loopback regardless of the name. Ethernet-type
    links are classified by the documented name-prefix mapping above; a name
    that matches nothing is reported as "Other" — never a guess.
    """
    if link_type == "loopback" or name == "lo":
        return "Loopback"
    lowered = name.lower()
    for prefix, kind in _INTERFACE_TYPE_BY_PREFIX:
        if lowered.startswith(prefix):
            return kind
    return "Other"


def _split_address(token: str) -> tuple[str, int | None] | None:
    """``addr/prefix`` -> (addr, prefix); a bare valid address keeps None.

    The prefix is preserved only when the device published a valid one
    (0-32 for IPv4, 0-128 for IPv6); an invalid prefix makes the whole
    token malformed -> None, and no subnet mask is ever inferred.
    """
    address, sep, prefix_text = token.partition("/")
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return None
    if not sep:
        return address, None
    try:
        prefix = int(prefix_text)
    except ValueError:
        return None
    if parsed.version == 4:
        if not 0 <= prefix <= 32:
            return None
    elif not 0 <= prefix <= 128:
        return None
    return address, prefix


def parse_ip_addr(text: str) -> tuple[NetworkInterfaceInfo, ...] | None:
    """Parse ``ip addr`` output into one ``NetworkInterfaceInfo`` per block.

    Each interface block is ``<index>: <name>: <flags> mtu ...`` followed by
    indented ``link/``, ``inet`` and ``inet6`` lines. Blocks are kept in
    source order; a block whose header does not match, malformed address
    tokens and unreadable MAC lines are skipped rather than failing the
    parse. No header at all -> None (the source is unusable).
    """
    interfaces: list[NetworkInterfaceInfo] = []
    current: NetworkInterfaceInfo | None = None
    for raw in text.splitlines():
        header = _INTERFACE_HEADER_RE.match(raw)
        if header is not None:
            if current is not None:
                interfaces.append(current)
            name, flags = header.group(1), header.group(2)
            current = NetworkInterfaceInfo(
                name=name,
                interface_type=_classify_interface(name, ""),
                is_up="UP" in flags,
                is_default_route=False,
                mac_address=None,
                ipv4_addresses=(),
                ipv6_addresses=(),
            )
            continue
        if current is None:
            continue
        link = _LINK_RE.match(raw)
        if link is not None:
            address = link.group(1).lower()
            if (
                current.interface_type != "Loopback"
                and address != _MAC_PLACEHOLDER
            ):
                current = _replace_interface(current, mac_address=address)
            continue
        inet6 = _INET6_RE.match(raw)
        if inet6 is not None:
            parsed = _split_address(inet6.group(1))
            if parsed is not None:
                current = _replace_interface(
                    current,
                    ipv6_addresses=current.ipv6_addresses
                    + (_cidr(parsed[0], parsed[1]),),
                )
            continue
        inet = _INET_RE.match(raw)
        if inet is not None:
            parsed = _split_address(inet.group(1))
            if parsed is not None:
                current = _replace_interface(
                    current,
                    ipv4_addresses=current.ipv4_addresses
                    + (_cidr(parsed[0], parsed[1]),),
                )
    if current is not None:
        interfaces.append(current)
    return tuple(interfaces) or None


def _replace_interface(
    current: NetworkInterfaceInfo, **changes
) -> NetworkInterfaceInfo:
    """Rebuild a frozen interface with ``changes`` applied (small helper)."""
    return dataclasses.replace(current, **changes)


def _cidr(address: str, prefix: int | None) -> str:
    """``(address, prefix)`` -> ``"address/prefix"`` (bare when no prefix)."""
    return address if prefix is None else f"{address}/{prefix}"


def mark_default_route(
    interfaces: tuple[NetworkInterfaceInfo, ...], default_interface: str | None
) -> tuple[NetworkInterfaceInfo, ...]:
    """Flag the interface that carries the default route, if any.

    The default interface comes from ``ip route`` — it is never assumed to
    be ``wlan0``. When there is no default route at all, every interface is
    flagged False.
    """
    if default_interface is None:
        return tuple(
            _replace_interface(iface, is_default_route=False) for iface in interfaces
        )
    return tuple(
        _replace_interface(
            iface, is_default_route=(iface.name == default_interface)
        )
        for iface in interfaces
    )


def collect_ipv4_addresses(
    interfaces: tuple[NetworkInterfaceInfo, ...],
) -> tuple[str, ...] | None:
    """IPv4 addresses (prefix stripped) of non-loopback interfaces only.

    Loopback (127.0.0.1) is not a network address and is kept out of the
    convenience list; the interface model still carries it structurally.
    """
    addresses = [
        _strip_prefix(cidr)
        for iface in interfaces
        if iface.interface_type != "Loopback"
        for cidr in iface.ipv4_addresses
    ]
    return tuple(addresses) or None


def collect_ipv6_addresses(
    interfaces: tuple[NetworkInterfaceInfo, ...],
) -> tuple[str, ...] | None:
    """IPv6 addresses (prefix stripped) of non-loopback interfaces only."""
    addresses = [
        _strip_prefix(cidr)
        for iface in interfaces
        if iface.interface_type != "Loopback"
        for cidr in iface.ipv6_addresses
    ]
    return tuple(addresses) or None


def _strip_prefix(cidr: str) -> str:
    return cidr.partition("/")[0]


#: ``default via <gateway> dev <iface> [proto X] [metric N]`` — or, for
#: link-scope defaults (typical of VPNs), ``default dev <iface>``.
_DEFAULT_ROUTE_RE = re.compile(
    r"^\s*default\s+(?:via\s+(\S+)\s+)?dev\s+(\S+)(?:.*\bmetric\s+(\d+))?"
)


def parse_ip_route(text: str) -> tuple[str | None, str | None, int | None] | None:
    """The default route from ``ip route`` as (gateway, interface, metric).

    Only a line whose first token is ``default`` is considered; non-default
    routes are ignored. The gateway must be a valid IP address — one is
    never inferred from anything else. No parseable default route -> None.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or not line.startswith("default"):
            continue
        match = _DEFAULT_ROUTE_RE.match(line)
        if match is None:
            continue
        gateway_text = match.group(1)
        interface = match.group(2).strip() or None
        gateway: str | None = None
        if gateway_text is not None:
            try:
                ipaddress.ip_address(gateway_text)
            except ValueError:
                continue
            gateway = gateway_text
        metric: int | None = None
        if match.group(3) is not None:
            try:
                metric = int(match.group(3))
            except ValueError:
                metric = None
        return gateway, interface, metric
    return None


# ---------------------------------------------------------------------------
# Wi-Fi state (dumpsys wifi): SNAPSHOT of a POTENTIALLY DYNAMIC state
# ---------------------------------------------------------------------------
# Collected once per connection session; continuous Wi-Fi monitoring would
# belong to the network monitor package in a later phase, not here.
#
# ``dumpsys wifi`` prints the current connection two ways across Android
# versions: an ``mWifiInfo ...`` line (older) or a ``Current network info:``
# section (newer). Scan results use lowercase ``frequency:``/``level:``
# tokens and are NOT the connected network, so the current-connection line
# is the only source for SSID/BSSID/link speed/frequency/RSSI. When Android
# redacts the SSID it prints ``<ssid>`` — reported as None, never guessed.

_WIFI_STATE_RE = re.compile(r"(?i)Wi-Fi is (enabled|disabled)\b")
_WIFI_ENABLED_TOKEN_RE = re.compile(r"(?i)mWifiEnabled\s*=\s*(true|false)\b")
_WIFI_NETWORK_STATE_RE = re.compile(r"state:\s*([A-Z]+)")
_WIFI_CONNECTED_STATES = frozenset({"CONNECTED"})
_WIFI_DISCONNECTED_STATES = frozenset({"DISCONNECTED"})
#: The connected-network info line: ``mWifiInfo SSID: ...`` or
#: ``Current network info: SSID: ...`` — whichever comes first wins.
_CURRENT_WIFI_LINE_RE = re.compile(
    r"^(?:mWifiInfo|Current network info:)(.*)$"
)
_SSID_QUOTED_RE = re.compile(r'SSID:\s*"([^"]*)"')
_SSID_REDACTED_RE = re.compile(r"SSID:\s*<[^>]*>")
_BSSID_RE = re.compile(r"BSSID:\s*([0-9A-Fa-f:]+)")
_FREQUENCY_RE = re.compile(r"Frequency:\s*(\d+)\s*(?:MHz)?")
_FREQUENCY_TOKEN_RE = re.compile(r"mFrequency\s*=\s*(\d+)")
_LINK_SPEED_RE = re.compile(r"Link speed:\s*([0-9.]+)\s*Mbps")
_LINK_SPEED_TOKEN_RE = re.compile(r"mLinkSpeed\s*=\s*([0-9.]+)")
_RSSI_RE = re.compile(r"RSSI:\s*(-?\d+)")
_RSSI_TOKEN_RE = re.compile(r"mRssi\s*=\s*(-?\d+)")
#: Plausible RSSI range in dBm; anything outside is treated as malformed.
_RSSI_MIN = -150
_RSSI_MAX = 0


def _current_wifi_info_line(text: str) -> str | None:
    """The current-connection info line of ``dumpsys wifi``, or None."""
    for raw in text.splitlines():
        match = _CURRENT_WIFI_LINE_RE.match(raw.strip())
        if match is not None:
            return match.group(1)
    return None


def parse_wifi_enabled(text: str) -> bool | None:
    """Wi-Fi radio state from ``dumpsys wifi`` (enabled/disabled).

    ``Wi-Fi is enabled`` / ``Wi-Fi is disabled`` lines are canonical;
    ``mWifiEnabled=true|false`` is the fallback for older builds. Neither
    token present -> None.
    """
    match = _WIFI_STATE_RE.search(text)
    if match is not None:
        return match.group(1).lower() == "enabled"
    match = _WIFI_ENABLED_TOKEN_RE.search(text)
    if match is not None:
        return match.group(1).lower() == "true"
    return None


def parse_wifi_connected(text: str) -> bool | None:
    """Connected-to-AP state from the WIFI network state of ``dumpsys wifi``.

    Only the state of the WIFI network is considered (``type: WIFI`` lines
    are not required to match — the state token is the same shape across
    versions). CONNECTED -> True, DISCONNECTED -> False; intermediate
    states (CONNECTING, ...) and absent tokens -> None.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if "type: WIFI" not in line and "NetworkInfo:" not in line:
            continue
        match = _WIFI_NETWORK_STATE_RE.search(line)
        if match is None:
            continue
        state = match.group(1).upper()
        if state in _WIFI_CONNECTED_STATES:
            return True
        if state in _WIFI_DISCONNECTED_STATES:
            return False
    return None


def parse_wifi_ssid(text: str) -> str | None:
    """The connected SSID from the current-connection line of ``dumpsys wifi``.

    A quoted name is unquoted; empty, ``<ssid>`` (Android's redaction
    placeholder), ``"<unknown ssid>"`` and absent values -> None. The SSID
    is never inferred from anything else.
    """
    line = _current_wifi_info_line(text)
    if line is None:
        return None
    if _SSID_REDACTED_RE.search(line) is not None:
        return None
    match = _SSID_QUOTED_RE.search(line)
    if match is None:
        return None
    value = match.group(1).strip()
    if not value or value.startswith("<") and value.endswith(">"):
        return None
    return value


def parse_wifi_bssid(text: str) -> str | None:
    """The connected BSSID from ``dumpsys wifi``, normalized as a MAC.

    Reuses ``parse_mac_address``: the ``02:00:00:00:00:00`` placeholder and
    malformed values -> None. Privacy-sensitive; never logged raw.
    """
    line = _current_wifi_info_line(text)
    if line is None:
        return None
    match = _BSSID_RE.search(line)
    if match is None:
        return None
    return parse_mac_address(match.group(1))


def parse_wifi_frequency(text: str) -> int | None:
    """Wi-Fi frequency in MHz from ``dumpsys wifi``; positive int, else None.

    ``Frequency: 5180MHz`` on the current-connection line is canonical;
    ``mFrequency=5180`` is the fallback. Zero, negative and malformed -> None;
    the value is never converted into a Wi-Fi standard name.
    """
    line = _current_wifi_info_line(text)
    if line is not None:
        match = _FREQUENCY_RE.search(line)
        if match is not None:
            try:
                value = int(match.group(1))
            except ValueError:
                value = -1
            return value if value > 0 else None
    match = _FREQUENCY_TOKEN_RE.search(text)
    if match is not None:
        try:
            value = int(match.group(1))
        except ValueError:
            value = -1
        return value if value > 0 else None
    return None


def parse_wifi_link_speed(text: str) -> float | None:
    """Wi-Fi link speed in Mbps from ``dumpsys wifi``; positive, else None.

    ``Link speed: 866Mbps`` on the current-connection line is canonical;
    ``mLinkSpeed=866`` is the fallback. This is the radio link rate — NOT
    an internet speed measurement. Zero/negative/malformed -> None.
    """
    line = _current_wifi_info_line(text)
    if line is not None:
        match = _LINK_SPEED_RE.search(line)
        if match is not None:
            try:
                value = float(match.group(1))
            except ValueError:
                value = -1.0
            return value if value > 0 else None
    match = _LINK_SPEED_TOKEN_RE.search(text)
    if match is not None:
        try:
            value = float(match.group(1))
        except ValueError:
            value = -1.0
        return value if value > 0 else None
    return None


def parse_wifi_rssi(text: str) -> int | None:
    """Wi-Fi RSSI in dBm from ``dumpsys wifi``; raw numeric value.

    ``RSSI: -45`` on the current-connection line is canonical; ``mRssi=-45``
    is the fallback. Values outside the plausible dBm range (-150..0) are
    malformed -> None. The value is never converted to "Excellent"/"Good" —
    presentation belongs to the GUI.
    """
    line = _current_wifi_info_line(text)
    candidates: list[int] = []
    if line is not None:
        match = _RSSI_RE.search(line)
        if match is not None:
            try:
                candidates.append(int(match.group(1)))
            except ValueError:
                pass
    match = _RSSI_TOKEN_RE.search(text)
    if match is not None:
        try:
            candidates.append(int(match.group(1)))
        except ValueError:
            pass
    for value in candidates:
        if _RSSI_MIN <= value <= _RSSI_MAX:
            return value
    return None


# ---------------------------------------------------------------------------
# Connectivity (dumpsys connectivity): active transport + DNS
# ---------------------------------------------------------------------------
# Also a once-per-session SNAPSHOT of a dynamic state.

#: Transport token -> human label. Tokens not listed map to "Other".
_TRANSPORT_LABELS = {
    "WIFI": "Wi-Fi",
    "CELLULAR": "Cellular",
    "ETHERNET": "Ethernet",
    "VPN": "VPN",
    "BLUETOOTH": "Bluetooth",
    "WIFI_AWARE": "Wi-Fi Aware",
    "LOWPAN": "Low-PAN",
}
_ACTIVE_NETWORK_RE = re.compile(r"^\s*Active default network:\s*(.*)$")
#: Inline form (Android 12+): ``NetworkAgentInfo{ [WIFI () - 100] ...``.
_INLINE_NETWORK_RE = re.compile(r"\[([A-Z_]+) \(\) - (\d+)\]")
_BARE_NETWORK_ID_RE = re.compile(r"(\d+)\s*$")
#: Block header form (Android 11 and older): ``100 NetworkAgentInfo{ [WIFI () - 100]``.
_BLOCK_HEADER_RE = re.compile(r"NetworkAgentInfo\{\s*\[([A-Z_]+) \(\) - (\d+)\]")
#: DNS lists inside LinkProperties; token names vary across Android versions.
_DNS_LIST_RES = (
    re.compile(r"DnsAddresses:\s*\[([^\]]*)\]"),
    re.compile(r"DnsServers:\s*\[([^\]]*)\]"),
    re.compile(r"DNS servers:\s*\[([^\]]*)\]"),
)


def parse_active_transport(text: str) -> str | None:
    """The active default transport label from ``dumpsys connectivity``.

    Both known formats are handled: the inline ``NetworkAgentInfo{ [WIFI () - 100]``
    form and the bare ``Active default network: 100`` form whose transport is
    read from the matching ``NetworkAgentInfo`` block header. ``null``/missing
    -> None; an unrecognized transport token -> "Other".
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("Active default network:"):
            continue
        rest = line[len("Active default network:") :].strip()
        inline = _INLINE_NETWORK_RE.search(rest)
        if inline is not None:
            return _TRANSPORT_LABELS.get(inline.group(1), "Other")
        if rest.lower() == "null":
            return None
        bare = _BARE_NETWORK_ID_RE.search(rest)
        if bare is None:
            return None
        network_id = bare.group(1)
        for block_raw in text.splitlines():
            block = _BLOCK_HEADER_RE.search(block_raw)
            if block is not None and block.group(2) == network_id:
                return _TRANSPORT_LABELS.get(block.group(1), "Other")
        return None
    return None


def parse_connectivity_dns(text: str) -> tuple[str, ...] | None:
    """DNS servers of the active default network from ``dumpsys connectivity``.

    With the inline active-network form, the DNS list is read from that same
    line; with the bare-id form, from the ``LinkProperties`` block of the
    matching network (ending at the next ``NetworkAgentInfo`` header). Every
    entry must be a valid IP address — malformed entries are dropped and an
    all-malformed/absent list -> None. DNS is never reported unless the
    source clearly establishes it.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("Active default network:"):
            continue
        rest = line[len("Active default network:") :].strip()
        inline = _INLINE_NETWORK_RE.search(rest)
        if inline is not None:
            return _parse_dns_list(rest)
        if rest.lower() == "null":
            return None
        bare = _BARE_NETWORK_ID_RE.search(rest)
        if bare is None:
            return None
        network_id = bare.group(1)
        lines = text.splitlines()
        for index, block_raw in enumerate(lines):
            block = _BLOCK_HEADER_RE.search(block_raw)
            if block is None or block.group(2) != network_id:
                continue
            for following in lines[index + 1 :]:
                if _BLOCK_HEADER_RE.search(following) is not None:
                    break
                dns = _parse_dns_list(following)
                if dns is not None:
                    return dns
            return None
        return None
    return None


def _parse_dns_list(text: str) -> tuple[str, ...] | None:
    """The first valid DNS list in *text*; malformed entries are dropped."""
    for pattern in _DNS_LIST_RES:
        match = pattern.search(text)
        if match is None:
            continue
        servers: list[str] = []
        for entry in match.group(1).split(","):
            candidate = entry.strip()
            if not candidate:
                continue
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                continue
            servers.append(candidate)
        return tuple(servers) or None
    return None


# ---------------------------------------------------------------------------
# VPN (dumpsys vpn)
# ---------------------------------------------------------------------------
# The VpnManagerService dump is the authoritative VPN state source: it
# prints ``VPN state: connected|disconnected`` (case-insensitive). The
# interface name is read from the ``interface:`` line inside the connected
# block — this is the ONLY place a VPN interface is derived from, never
# from the interface name alone.

_VPN_STATE_RE = re.compile(r"(?im)^\s*vpn state:\s*(connected|disconnected)\b")
_VPN_INTERFACE_RE = re.compile(r"(?im)^\s*interface:\s*(\S+)")


def parse_vpn_state(text: str) -> tuple[bool | None, str | None]:
    """VPN state as (active, interface) from ``dumpsys vpn``.

    ``(True, iface)`` when a VPN is connected (interface may be None if the
    dump does not expose it), ``(False, None)`` when explicitly disconnected,
    ``(None, None)`` when the state is not exposed at all.
    """
    match = _VPN_STATE_RE.search(text)
    if match is None:
        return (None, None)
    if match.group(1).lower() != "connected":
        return (False, None)
    iface_match = _VPN_INTERFACE_RE.search(text)
    return (True, iface_match.group(1) if iface_match is not None else None)


# ---------------------------------------------------------------------------
# Security posture (Phase 2F)
# ---------------------------------------------------------------------------
# Evidence-based facts only. None means UNKNOWN (missing, malformed or
# contradictory evidence). Unknown is never collapsed into a positive or
# negative claim: a failed ``getenforce`` read is NOT "disabled", and the
# absence of root evidence is NOT "not rooted".
#: Canonical SELinux mode tokens (``getenforce`` output, case-insensitive).
_SELINUX_STATES = frozenset({"enforcing", "permissive", "disabled"})

#: Canonical Android Verified Boot state tokens (``ro.boot.verifiedbootstate``).
_VERIFIED_BOOT_STATES = frozenset({"green", "yellow", "orange", "red"})

#: Canonical dm-verity mode tokens (``ro.boot.veritymode``).
_VERITY_MODES = frozenset({"enforcing", "eio", "logging", "disabled"})

#: Canonical encryption state tokens (``ro.crypto.state``).
_ENCRYPTION_STATES = frozenset({"encrypted", "unencrypted"})

#: Canonical encryption model tokens (``ro.crypto.type``).
_ENCRYPTION_TYPES = frozenset({"file", "block"})

#: Numeric/boolean property values accepted by :func:`parse_property_bool`.
_BOOL_PROPERTY_VALUES = {
    "1": True,
    "0": False,
    "true": True,
    "false": False,
}

#: Marker printed by the collector's read-only ``su`` check when ``su`` is
#: not on PATH; the command always exits 0 so the result is unambiguous.
SU_NOT_FOUND = "__SU_NOT_FOUND__"

#: Strict YYYY-MM-DD security patch level.
_SECURITY_PATCH_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

_UID_RE = re.compile(r"\buid=(\d+)")


def _normalize_token(value: str | None) -> str | None:
    """Lowercase, strip, and collapse to None when empty."""
    if value is None:
        return None
    token = value.strip().lower()
    return token or None


def parse_selinux_status(text: str | None) -> str | None:
    """SELinux mode from ``getenforce`` output.

    Returns the lowercase canonical token ("enforcing" / "permissive" /
    "disabled") or None when the output is malformed. A failed or missing
    read is None (UNKNOWN) — it is never interpreted as "disabled".
    """
    token = _normalize_token(text)
    if token in _SELINUX_STATES:
        return token
    return None


def parse_verified_boot_state(value: str | None) -> str | None:
    """Android Verified Boot state from ``ro.boot.verifiedbootstate``.

    Returns one of "green" / "yellow" / "orange" / "red" (Android's own
    states) or None when the property is missing or malformed. This is one
    security signal only — it is never converted into a "secure"/"rooted"
    claim.
    """
    token = _normalize_token(value)
    if token in _VERIFIED_BOOT_STATES:
        return token
    return None


def parse_bootloader_locked(
    flash_locked: str | None, vbmeta_state: str | None
) -> bool | None:
    """Bootloader lock state: True locked, False unlocked, None UNKNOWN.

    ``ro.boot.flash.locked`` is the primary source ("1"/"0", or "true"/
    "false" on some OEM builds); ``ro.boot.vbmeta.device_state``
    ("locked"/"unlocked") corroborates it. When both sources are present
    and disagree the result is None — contradictory evidence is UNKNOWN,
    never resolved by guessing.
    """
    primary = None
    if flash_locked is not None:
        primary = _BOOL_PROPERTY_VALUES.get(flash_locked.strip().lower())
    secondary = None
    if vbmeta_state is not None:
        token = vbmeta_state.strip().lower()
        if token == "locked":
            secondary = True
        elif token == "unlocked":
            secondary = False
    if primary is not None and secondary is not None:
        return primary if primary == secondary else None
    if primary is not None:
        return primary
    return secondary


def parse_root_status(id_text: str | None, su_text: str | None) -> str | None:
    """Root evidence state: "ROOT_EVIDENCE" / "NO_ROOT_EVIDENCE" / None.

    Evidence sources (read-only, never executing ``su`` itself):
      * ``id`` — a session running as ``uid=0`` is direct root evidence.
      * the ``su``-on-PATH check — a located executable path is root
        evidence; the ``SU_NOT_FOUND`` marker alone documents absence of
        evidence. Shell error text ("...: not found") is NOT a path and is
        treated as ambiguous — it never becomes root evidence.

    Returns None (UNKNOWN) when no source produced a usable result, or
    when the evidence is otherwise ambiguous. "NO_ROOT_EVIDENCE" is only a
    statement about evidence found — it never asserts the device is not
    rooted.
    """
    result: str | None = None
    if id_text is not None:
        uid_match = _UID_RE.search(id_text)
        if uid_match is not None:
            if uid_match.group(1) == "0":
                return "ROOT_EVIDENCE"
            result = "NO_ROOT_EVIDENCE"
    if su_text is not None:
        token = su_text.strip()
        if token and token != SU_NOT_FOUND:
            if " " not in token or token.startswith("/"):
                return "ROOT_EVIDENCE"
        elif token == SU_NOT_FOUND:
            result = "NO_ROOT_EVIDENCE"
    return result


def parse_security_patch_date(value: str | None) -> date | None:
    """Security patch level as a validated date (strict YYYY-MM-DD).

    Malformed values (bad format, impossible month/day) yield None; the
    value is never repaired, guessed or converted into a security score.
    """
    if value is None:
        return None
    match = _SECURITY_PATCH_RE.match(value.strip())
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_property_bool(value: str | None) -> bool | None:
    """Normalize a 0/1 or true/false build property; None when malformed.

    Used for ``ro.debuggable`` and ``ro.secure``. A missing or malformed
    property is None (UNKNOWN) — never guessed from the build type.
    """
    if value is None:
        return None
    return _BOOL_PROPERTY_VALUES.get(value.strip().lower())


def parse_encryption_state(value: str | None) -> str | None:
    """``ro.crypto.state``: "encrypted" / "unencrypted" / None (UNKNOWN)."""
    token = _normalize_token(value)
    if token in _ENCRYPTION_STATES:
        return token
    return None


def parse_encryption_type(value: str | None) -> str | None:
    """``ro.crypto.type``: "file" / "block" / None (UNKNOWN)."""
    token = _normalize_token(value)
    if token in _ENCRYPTION_TYPES:
        return token
    return None


def parse_verity_mode(value: str | None) -> str | None:
    """``ro.boot.veritymode``: enforcing / eio / logging / disabled / None.

    One dm-verity signal; None (UNKNOWN) when missing or malformed. It is
    never extended into a whole-device integrity verdict.
    """
    token = _normalize_token(value)
    if token in _VERITY_MODES:
        return token
    return None