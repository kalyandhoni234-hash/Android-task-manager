"""Parsers for raw device-information command output.

Each parser is a pure function: raw text in, structured value out. Every
parser tolerates malformed or unexpected output by returning ``None``
rather than raising — a bad value on one property must never break the
rest of the device page.
"""

from __future__ import annotations

import re

from .models import StorageInfo

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