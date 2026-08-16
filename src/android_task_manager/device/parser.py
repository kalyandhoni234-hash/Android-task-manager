"""Parsers for raw device-information command output.

Each parser is a pure function: raw text in, structured value out. Every
parser tolerates malformed or unexpected output by returning ``None``
rather than raising — a bad value on one property must never break the
rest of the device page.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

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