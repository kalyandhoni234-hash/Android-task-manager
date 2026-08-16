"""Evidence-based diagnostic rules.

Every rule is a pure, deterministic, side-effect-free function that takes
already-collected snapshot data and returns the findings it can honestly
support — or nothing.

Core invariants:

- **No new ADB polling.** Rules consume only the structured snapshots the
  monitoring/device collectors already produce.
- **Never guess.** A rule fires only when the collected fields support
  the claim it makes.
- **UNKNOWN ≠ FALSE.** ``None`` / missing / malformed data produces no
  finding. A rule must never treat "not collected" as "normal" or as
  "wrong".
- **No scores.** Each finding is self-contained and explainable.

Thresholds live in ``thresholds.py`` (mirroring the canonical values in
``gui/thresholds.py`` where they exist). Boundary semantics match the
existing GUI classifiers exactly: elevated is strictly-greater, critical
is greater-or-equal.
"""

from __future__ import annotations

from ..battery.models import BatteryHealth, BatterySnapshot, BatteryStatus
from ..cpu.models import CPUSnapshot
from ..device.models import DeviceInformation
from ..memory.models import MemorySnapshot
from ..terminal.renderer import format_kib
from .models import DiagnosticCategory, DiagnosticFinding, DiagnosticSeverity
from .thresholds import (
    CPU_CRITICAL_PERCENT,
    CPU_ELEVATED_PERCENT,
    MEMORY_CRITICAL_PERCENT,
    MEMORY_ELEVATED_PERCENT,
    STORAGE_CRITICAL_PERCENT,
    STORAGE_ELEVATED_PERCENT,
    TEMPERATURE_CRITICAL_C,
    TEMPERATURE_ELEVATED_C,
)

# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------


def battery_temperature(battery: BatterySnapshot) -> tuple[DiagnosticFinding, ...]:
    """Battery temperature against the documented thresholds.

    ``temperature_c is None`` (not collected) -> no finding.
    Boundary: ``> TEMPERATURE_ELEVATED_C`` is a WARNING, ``>=
    TEMPERATURE_CRITICAL_C`` is CRITICAL (mirrors ``gui.thresholds``).
    """
    temperature = battery.temperature_c
    if temperature is None:
        return ()
    if temperature >= TEMPERATURE_CRITICAL_C:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.BATTERY,
                title="Critical battery temperature",
                what="The battery is reporting a critically high temperature.",
                why=(
                    "The reported temperature reaches the critical threshold "
                    f"({TEMPERATURE_CRITICAL_C:g} °C)."
                ),
                evidence=f"Temperature: {temperature:.1f} °C",
                recommended_action=(
                    "Stop heavy workloads and charging immediately; investigate "
                    "prolonged overheating — it can damage the battery."
                ),
            ),
        )
    if temperature > TEMPERATURE_ELEVATED_C:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.BATTERY,
                title="Elevated battery temperature",
                what="The battery is running hotter than expected.",
                why=(
                    "The reported temperature exceeds the elevated threshold "
                    f"({TEMPERATURE_ELEVATED_C:g} °C)."
                ),
                evidence=f"Temperature: {temperature:.1f} °C",
                recommended_action=(
                    "Avoid heavy load and direct sunlight while charging; if the "
                    "temperature stays high, let the device cool before further use."
                ),
            ),
        )
    return ()


def battery_health(battery: BatterySnapshot) -> tuple[DiagnosticFinding, ...]:
    """Battery health states with unambiguous Android semantics.

    ``BatteryHealth.UNKNOWN`` (or an unreadable state) -> no finding.
    OVERHEAT / DEAD -> CRITICAL; COLD / OVER_VOLTAGE /
    UNSPECIFIED_FAILURE -> WARNING.
    """
    health = battery.health
    if health is BatteryHealth.OVERHEAT:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.BATTERY,
                title="Battery reports overheat",
                what="The battery itself reports an overheated state.",
                why="The device reports battery health 'Overheat'.",
                evidence="Health: Overheat",
                recommended_action=(
                    "Let the device cool before further use and monitor the "
                    "temperature over a sustained period."
                ),
            ),
        )
    if health is BatteryHealth.DEAD:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.BATTERY,
                title="Battery reports dead state",
                what="The battery reports a dead state.",
                why="The device reports battery health 'Dead'.",
                evidence="Health: Dead",
                recommended_action=(
                    "Service or replace the battery; keep the device on a stable "
                    "power source in the meantime."
                ),
            ),
        )
    if health is BatteryHealth.COLD:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.BATTERY,
                title="Battery reports cold state",
                what="The battery is reporting an unusually cold state.",
                why="The device reports battery health 'Cold'.",
                evidence="Health: Cold",
                recommended_action=(
                    "Warm the device to normal operating temperature before "
                    "relying on its battery readings."
                ),
            ),
        )
    if health is BatteryHealth.OVER_VOLTAGE:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.BATTERY,
                title="Battery reports over-voltage",
                what="The battery is reporting an over-voltage state.",
                why="The device reports battery health 'Over voltage'.",
                evidence="Health: Over voltage",
                recommended_action=(
                    "Stop charging and investigate the charger and cable; "
                    "over-voltage can indicate faulty charging hardware."
                ),
            ),
        )
    if health is BatteryHealth.UNSPECIFIED_FAILURE:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.BATTERY,
                title="Battery reports an unspecified failure",
                what="The battery is reporting a failure state without details.",
                why="The device reports battery health 'Unspecified failure'.",
                evidence="Health: Unspecified failure",
                recommended_action=(
                    "Investigate battery health further; the device reports a "
                    "failure state without additional detail."
                ),
            ),
        )
    return ()


def battery_charging(battery: BatterySnapshot) -> tuple[DiagnosticFinding, ...]:
    """Charging-state observations from status + power-source flags.

    A plain discharge (no power source flag set) is informational only.
    A discharge while a power source is reported is contradictory evidence
    and is flagged as such — never silently resolved in either direction.
    """
    if battery.status is not BatteryStatus.DISCHARGING:
        return ()
    powered = (
        battery.ac_powered is True
        or battery.usb_powered is True
        or battery.wireless_powered is True
    )
    if powered:
        sources = [
            name
            for name, flag in (
                ("AC", battery.ac_powered),
                ("USB", battery.usb_powered),
                ("Wireless", battery.wireless_powered),
            )
            if flag is True
        ]
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.BATTERY,
                title="Contradictory charging state reported",
                what=(
                    "The device reports discharging while also reporting an "
                    "active power source."
                ),
                why=(
                    "Charging status is 'Discharging' but a power-source flag "
                    "is set — the two claims cannot both hold."
                ),
                evidence=(
                    f"Status: Discharging · Power source: {' + '.join(sources)}"
                ),
                recommended_action=(
                    "Reconnect the device or cable; if the state persists, the "
                    "reported charging data is unreliable."
                ),
            ),
        )
    return (
        DiagnosticFinding(
            severity=DiagnosticSeverity.INFO,
            category=DiagnosticCategory.BATTERY,
            title="Battery is discharging",
            what="The battery is currently discharging.",
            why=(
                "Charging status reports 'Discharging' with no active power "
                "source reported."
            ),
            evidence="Status: Discharging",
            recommended_action="Charge the device if the battery level is low.",
        ),
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def storage_utilization(
    device: DeviceInformation,
) -> tuple[DiagnosticFinding, ...]:
    """Used share of the internal storage volume (``/data``).

    ``device.storage`` is None (not collected) or ``used_percent`` is None
    (non-positive total) -> no finding.
    Boundary: ``> STORAGE_ELEVATED_PERCENT`` is a WARNING, ``>=
    STORAGE_CRITICAL_PERCENT`` is CRITICAL.
    """
    storage = device.storage
    if storage is None:
        return ()
    percent = storage.used_percent
    if percent is None:
        return ()
    if percent >= STORAGE_CRITICAL_PERCENT:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.STORAGE,
                title="Critical storage utilization",
                what="Internal storage is almost completely full.",
                why=(
                    "Used storage reaches the critical threshold "
                    f"({STORAGE_CRITICAL_PERCENT:g}%)."
                ),
                evidence=f"{storage.mount} usage: {percent:.0f}%",
                recommended_action=(
                    "Free space promptly — low free storage can break app "
                    "updates and system operations."
                ),
            ),
        )
    if percent > STORAGE_ELEVATED_PERCENT:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.STORAGE,
                title="High storage utilization",
                what="Internal storage is nearly full.",
                why=(
                    "Used storage exceeds the elevated threshold "
                    f"({STORAGE_ELEVATED_PERCENT:g}%)."
                ),
                evidence=f"{storage.mount} usage: {percent:.0f}%",
                recommended_action=(
                    "Free unnecessary files or uninstall unused applications."
                ),
            ),
        )
    return ()


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def memory_pressure(memory: MemorySnapshot) -> tuple[DiagnosticFinding, ...]:
    """Used share of total RAM as the memory-pressure indicator.

    ``used_kb`` is ``total - available`` (the snapshot's documented
    pressure baseline — never ``total - free``). A non-positive total or a
    negative used figure (contradictory data) -> no finding.
    Boundary: ``> MEMORY_ELEVATED_PERCENT`` is a WARNING, ``>=
    MEMORY_CRITICAL_PERCENT`` is CRITICAL.
    """
    total = memory.total_kb
    used = memory.used_kb
    if total <= 0 or used < 0:
        return ()
    percent = used / total * 100
    if percent >= MEMORY_CRITICAL_PERCENT:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.MEMORY,
                title="Critical memory pressure",
                what="Almost all of the device RAM is in use.",
                why=(
                    "Used memory reaches the critical threshold "
                    f"({MEMORY_CRITICAL_PERCENT:g}%)."
                ),
                evidence=(
                    f"Memory used: {percent:.0f}% of {format_kib(total)} "
                    f"(available {format_kib(memory.available_kb)})"
                ),
                recommended_action=(
                    "Close heavy applications; sustained pressure can force "
                    "the system to kill background processes."
                ),
            ),
        )
    if percent > MEMORY_ELEVATED_PERCENT:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.MEMORY,
                title="High memory pressure",
                what="Most of the device RAM is in use.",
                why=(
                    "Used memory exceeds the elevated threshold "
                    f"({MEMORY_ELEVATED_PERCENT:g}%)."
                ),
                evidence=(
                    f"Memory used: {percent:.0f}% of {format_kib(total)} "
                    f"(available {format_kib(memory.available_kb)})"
                ),
                recommended_action=(
                    "Close heavy applications; sustained pressure can slow the "
                    "device and force background process kills."
                ),
            ),
        )
    return ()


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------


def cpu_utilization(cpu: CPUSnapshot) -> tuple[DiagnosticFinding, ...]:
    """Aggregate CPU utilization against the documented thresholds.

    ``aggregate_utilization_percent is None`` (first sample — a delta has
    no baseline yet, or the read failed) -> no finding.
    Boundary: ``> CPU_ELEVATED_PERCENT`` is a WARNING, ``>=
    CPU_CRITICAL_PERCENT`` is CRITICAL.
    """
    utilization = cpu.aggregate_utilization_percent
    if utilization is None:
        return ()
    if utilization >= CPU_CRITICAL_PERCENT:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.CPU,
                title="Critical CPU utilization",
                what="The device CPU is saturated.",
                why=(
                    "Aggregate CPU utilization reaches the critical threshold "
                    f"({CPU_CRITICAL_PERCENT:g}%)."
                ),
                evidence=f"Aggregate CPU utilization: {utilization:.0f}%",
                recommended_action=(
                    "Check which processes are saturating the CPU; sustained "
                    "saturation may indicate a runaway process."
                ),
            ),
        )
    if utilization > CPU_ELEVATED_PERCENT:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.CPU,
                title="High CPU utilization",
                what="The device CPU is heavily utilized.",
                why=(
                    "Aggregate CPU utilization exceeds the elevated threshold "
                    f"({CPU_ELEVATED_PERCENT:g}%)."
                ),
                evidence=f"Aggregate CPU utilization: {utilization:.0f}%",
                recommended_action=(
                    "Identify the heaviest processes before concluding anything "
                    "— high utilization is not a fault by itself."
                ),
            ),
        )
    return ()


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def wifi_without_address(
    device: DeviceInformation,
) -> tuple[DiagnosticFinding, ...]:
    """Wi-Fi connected while no IP address was collected.

    Fires only when Wi-Fi is connected AND the address sources were read
    AND both came back empty (a failed DHCP lease is the common cause).
    ``None`` addresses mean "not collected" -> no finding. A connected
    link with no addresses is genuinely inconsistent with the device's
    own claim of connectivity.
    """
    if device.wifi_connected is not True:
        return ()
    if device.ipv4_addresses is None or device.ipv6_addresses is None:
        return ()
    if device.ipv4_addresses or device.ipv6_addresses:
        return ()
    return (
        DiagnosticFinding(
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.NETWORK,
            title="Wi-Fi connected without an IP address",
            what="The device reports a connected Wi-Fi link but has no IP address.",
            why=(
                "Wi-Fi reports 'connected', yet no IPv4 or IPv6 address was "
                "collected — a connected link without an address usually "
                "indicates a failed DHCP lease."
            ),
            evidence="Wi-Fi: Connected · IPv4: none · IPv6: none",
            recommended_action=(
                "Reconnect Wi-Fi or check the router's DHCP; if it persists, "
                "investigate the access point."
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

#: SELinux mode tokens with defined semantics (device/models.py).
_SELINUX_PERMISSIVE = "permissive"
_SELINUX_DISABLED = "disabled"

#: Verified Boot tokens with defined Android semantics (device/models.py).
_VERIFIED_BOOT_WEAKENED = {"yellow", "orange"}
_VERIFIED_BOOT_RED = "red"

#: dm-verity tokens that are weaker than "enforcing" (device/models.py).
_VERITY_WEAKENED = {"eio", "logging", "disabled"}


def selinux_mode(device: DeviceInformation) -> tuple[DiagnosticFinding, ...]:
    """SELinux mode: permissive -> WARNING, disabled -> CRITICAL.

    ``None`` (unreadable) -> no finding — an unknown mode is never
    interpreted as disabled.
    """
    mode = device.selinux_status
    if mode == _SELINUX_DISABLED:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.SECURITY,
                title="SELinux is disabled",
                what="SELinux is disabled on this device.",
                why=(
                    "The device reports 'disabled' — mandatory access control "
                    "is off."
                ),
                evidence="SELinux mode: disabled",
                recommended_action=(
                    "Investigate the device image; a disabled SELinux is not a "
                    "stock Android configuration."
                ),
            ),
        )
    if mode == _SELINUX_PERMISSIVE:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.SECURITY,
                title="SELinux is in permissive mode",
                what="SELinux is running in permissive mode.",
                why=(
                    "The device reports 'permissive' — policy violations are "
                    "logged, not blocked."
                ),
                evidence="SELinux mode: permissive",
                recommended_action=(
                    "Investigate why SELinux is not enforcing; on stock firmware "
                    "this usually indicates a modified or debug build."
                ),
            ),
        )
    return ()


def verified_boot(device: DeviceInformation) -> tuple[DiagnosticFinding, ...]:
    """Verified Boot state: yellow/orange -> WARNING, red -> CRITICAL.

    ``None`` or "green" -> no finding. The tokens keep Android's verbatim
    semantics (device/models.py); nothing is inferred beyond them.
    """
    state = device.verified_boot_state
    if state == _VERIFIED_BOOT_RED:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.SECURITY,
                title="Verified Boot verification failed",
                what="The boot chain failed verification.",
                why=(
                    "The device reports verified boot state 'red' — a failed "
                    "verification, not a trusted boot."
                ),
                evidence="Verified boot: red",
                recommended_action=(
                    "Investigate the device image; a red verified-boot state "
                    "indicates the boot chain did not verify."
                ),
            ),
        )
    if state in _VERIFIED_BOOT_WEAKENED:
        return (
            DiagnosticFinding(
                severity=DiagnosticSeverity.WARNING,
                category=DiagnosticCategory.SECURITY,
                title="Verified Boot is not fully green",
                what="The boot chain did not verify fully.",
                why=(
                    f"The device reports verified boot state '{state}' — the "
                    "boot path is not verified green."
                ),
                evidence=f"Verified boot: {state}",
                recommended_action=(
                    "Investigate the bootloader and boot-chain state; a "
                    "yellow/orange state usually accompanies an unlocked or "
                    "unverified boot path."
                ),
            ),
        )
    return ()


def bootloader_lock(device: DeviceInformation) -> tuple[DiagnosticFinding, ...]:
    """Unlocked bootloader -> WARNING; locked or unknown -> no finding."""
    if device.bootloader_locked is not False:
        return ()
    return (
        DiagnosticFinding(
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="Bootloader is unlocked",
            what="The device bootloader is unlocked.",
            why="The device reports an unlocked bootloader.",
            evidence="Bootloader: unlocked",
            recommended_action=(
                "Lock the bootloader if it was not intentionally unlocked; an "
                "unlocked bootloader weakens boot-chain guarantees."
            ),
        ),
    )


def root_evidence(device: DeviceInformation) -> tuple[DiagnosticFinding, ...]:
    """Observed root evidence -> WARNING (an indicator, never a verdict).

    ``NO_ROOT_EVIDENCE`` and ``None`` produce no finding: the absence of
    evidence is not evidence of absence.
    """
    if device.root_status != "ROOT_EVIDENCE":
        return ()
    return (
        DiagnosticFinding(
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="Root evidence detected",
            what="A root indicator was observed on the device.",
            why=(
                "The device reports root evidence (a root indicator was "
                "observed) — an indicator, not a verdict."
            ),
            evidence="Root evidence: detected",
            recommended_action=(
                "Investigate which process or binary triggered the indicator "
                "before drawing any conclusion."
            ),
        ),
    )


def debuggable_build(device: DeviceInformation) -> tuple[DiagnosticFinding, ...]:
    """Debuggable system build -> WARNING (a defined build signal).

    ``None`` (malformed or missing) or False -> no finding.
    """
    if device.debuggable is not True:
        return ()
    return (
        DiagnosticFinding(
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="Debuggable system build",
            what="The system image is debuggable.",
            why="The device reports 'ro.debuggable' — a debug build configuration.",
            evidence="Build: debuggable",
            recommended_action=(
                "Investigate the build provenance; debuggable system images "
                "are not stock production builds."
            ),
        ),
    )


def storage_encryption(device: DeviceInformation) -> tuple[DiagnosticFinding, ...]:
    """Unencrypted storage -> WARNING; encrypted or unknown -> no finding."""
    if device.encryption_state != "unencrypted":
        return ()
    return (
        DiagnosticFinding(
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="Storage encryption is disabled",
            what="The device reports unencrypted storage.",
            why=(
                "The device reports encryption state 'unencrypted' — data at "
                "rest is not protected by device encryption."
            ),
            evidence="Encryption: unencrypted",
            recommended_action=(
                "Investigate the device configuration; unencrypted storage "
                "weakens data-at-rest protection."
            ),
        ),
    )


def verity_mode(device: DeviceInformation) -> tuple[DiagnosticFinding, ...]:
    """Weakened dm-verity modes -> WARNING; enforcing or unknown -> none.

    ``eio`` and ``logging`` degrade enforcement (errors allowed / logged
    only); ``disabled`` turns integrity verification off. All three have
    defined semantics in device/models.py.
    """
    mode = device.verity_mode
    if mode not in _VERITY_WEAKENED:
        return ()
    return (
        DiagnosticFinding(
            severity=DiagnosticSeverity.WARNING,
            category=DiagnosticCategory.SECURITY,
            title="dm-verity integrity verification is weakened",
            what="Filesystem integrity verification is not fully enforcing.",
            why=(
                f"The device reports verity mode '{mode}' — weaker than "
                "'enforcing'."
            ),
            evidence=f"Verity mode: {mode}",
            recommended_action=(
                "Investigate the device image; weakened dm-verity means file "
                "integrity is not verified at boot."
            ),
        ),
    )


__all__ = [
    "battery_charging",
    "battery_health",
    "battery_temperature",
    "bootloader_lock",
    "cpu_utilization",
    "debuggable_build",
    "memory_pressure",
    "root_evidence",
    "selinux_mode",
    "storage_encryption",
    "storage_utilization",
    "verity_mode",
    "verified_boot",
    "wifi_without_address",
]