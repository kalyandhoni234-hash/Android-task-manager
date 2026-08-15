"""Normalized device-information models.

``DeviceInformation`` is the contract between the device collector (raw
``getprop`` / ``wm`` / ``df`` reads) and the GUI. Every field is optional:
``None`` means "this property was not readable on this device" — the GUI
must render it as N/A, never as a guess. Live operational data (battery,
memory, CPU state) is deliberately NOT part of this model: it is collected
by the existing battery/memory/cpu collectors and only mirrored onto the
Device page from those snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StorageInfo:
    """One mounted storage volume, in 1 KiB blocks (from ``df -k``)."""

    #: The mount point this volume represents, e.g. ``/data``.
    mount: str
    total_kb: int
    used_kb: int
    available_kb: int

    @property
    def used_percent(self) -> float | None:
        """Used share of total, or None when total is not positive."""
        if self.total_kb <= 0:
            return None
        return self.used_kb / self.total_kb * 100


@dataclass(frozen=True)
class DeviceInformation:
    """A structured snapshot of the connected device's identity.

    All fields are ``None`` when the property could not be retrieved
    (missing property, access restriction, OEM variation). Empty strings
    from the device are normalized to ``None``.
    """

    # -- Basic information ---------------------------------------------------
    manufacturer: str | None = None
    brand: str | None = None
    model: str | None = None
    device: str | None = None
    product: str | None = None
    board: str | None = None
    hardware: str | None = None
    #: SoC name, e.g. "MediaTek Helio P35" (ro.soc.*) — falls back to the
    #: raw platform token when no human SoC name is published.
    soc: str | None = None

    # -- Android / software --------------------------------------------------
    android_version: str | None = None
    api_level: str | None = None
    security_patch: str | None = None
    build_id: str | None = None
    build_number: str | None = None
    build_fingerprint: str | None = None
    kernel: str | None = None
    bootloader: str | None = None
    baseband: str | None = None

    # -- Hardware / CPU ------------------------------------------------------
    processor: str | None = None
    architecture: str | None = None
    #: Representative maximum CPU frequency in kHz (core 0 cpufreq node).
    max_frequency_khz: int | None = None

    # -- Display -------------------------------------------------------------
    resolution: str | None = None
    density_dpi: int | None = None
    refresh_rate_hz: float | None = None
    orientation: str | None = None

    # -- Storage -------------------------------------------------------------
    #: Internal shared storage (/data). Volumes are never silently combined.
    storage: StorageInfo | None = None

    # -- Identifiers (handled carefully; usually restricted) -----------------
    android_id: str | None = None
    wifi_mac: str | None = None
    bluetooth_mac: str | None = None