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
from datetime import datetime


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
    #: Build tags, e.g. "release-keys" (ro.build.tags).
    build_tags: str | None = None
    #: Build type, e.g. "user" (ro.build.type).
    build_type: str | None = None
    kernel: str | None = None
    #: Full kernel version line from ``uname -a`` (kernel + build number +
    #: build date), e.g. "Linux localhost 4.14.186+ #1 SMP PREEMPT ... aarch64".
    kernel_version: str | None = None
    bootloader: str | None = None
    baseband: str | None = None

    # -- Runtime state (one structured read per connection session) ----------
    #: Device uptime in seconds: the first token of ``/proc/uptime``. The
    #: raw float is kept; formatting is a presentation concern.
    uptime_seconds: float | None = None
    #: Boot time, DERIVED as (device wall clock − uptime) in UTC. It is an
    #: estimate that inherits the device clock's accuracy — never treated as
    #: an authoritative value. ``None`` when the derivation is unreliable
    #: (clock behind uptime, either input unreadable, or negative uptime).
    boot_time: datetime | None = None

    # -- Hardware / CPU ------------------------------------------------------
    processor: str | None = None
    architecture: str | None = None
    #: Representative maximum CPU frequency in kHz (core 0 cpufreq node).
    max_frequency_khz: int | None = None

    # -- CPU topology / static configuration --------------------------------
    #: Machine token from ``uname -a`` (e.g. "aarch64", "armv7l", "x86_64").
    cpu_architecture: str | None = None
    #: 64-bit capability derived from ``cpu_architecture`` via a documented
    #: mapping; ``None`` when the machine token is ambiguous (e.g. "armv8l").
    cpu_64bit: bool | None = None
    #: Supported ABIs (ro.product.cpu.abilist), in device order, de-duplicated.
    cpu_abis: tuple[str, ...] | None = None
    #: Total logical CPU cores (``/sys/devices/system/cpu/present``, falling
    #: back to the number of ``processor`` entries in /proc/cpuinfo).
    cpu_core_count: int | None = None
    #: Online logical CPU cores (``/sys/devices/system/cpu/online``).
    cpu_online_cores: int | None = None
    #: Offline cores, DERIVED as ``core_count − online_cores`` only when both
    #: are known and consistent; ``None`` otherwise.
    cpu_offline_cores: int | None = None
    #: CPU scaling governor of core 0 (e.g. "schedutil", "performance").
    cpu_governor: str | None = None
    #: Normalized instruction-set feature names from /proc/cpuinfo
    #: (``Features`` on ARM, ``flags`` on x86), in source order.
    cpu_features: tuple[str, ...] | None = None
    #: Current scaling frequency of core 0 in Hz (kHz source converted at
    #: parse time). One-time snapshot of a dynamic value; live per-core
    #: frequency is owned by the cpu monitor package.
    cpu_current_frequency_hz: float | None = None
    #: Core-0 scaling minimum frequency in Hz (scaling_min_freq, kHz source).
    cpu_min_frequency_hz: float | None = None
    #: Core-0 scaling maximum frequency in Hz (scaling_max_freq, kHz source;
    #: the operating-range ceiling — distinct from ``max_frequency_khz``,
    #: which is the core-0 hardware ceiling from cpuinfo_max_freq).
    cpu_max_frequency_hz: float | None = None

    # -- Battery (static facts only) --------------------------------------------
    # NOTE: dynamic battery data (percentage, charging state, source, health,
    # temperature, voltage, technology) is owned by the live battery monitor
    # (``BatterySnapshot``, sampled every 15 s) and mirrored onto the Device
    # page from those snapshots — never duplicated here.
    #: Design capacity of the battery (``charge_full_design``). Kept
    #: verbatim: the kernel convention is microamp-hours but OEMs vary, so
    #: no unit conversion is claimed (same policy as the live snapshot's
    #: ``charge_counter``).
    battery_design_capacity: int | None = None
    #: Battery charge cycle count (``cycle_count``); 0 is valid (new battery).
    battery_cycle_count: int | None = None

# -- GPU ------------------------------------------------------------------
    #: GPU vendor read from the ``dumpsys SurfaceFlinger`` GLES line (e.g.
    #: "Qualcomm", "ARM", "Imagination Technologies"). Only ever read from
    #: the device; never derived from the SoC/chipset.
    gpu_vendor: str | None = None
    #: GPU model as reported by the renderer string (e.g. "Adreno (TM) 610",
    #: "Mali-G76 MC4") — preserved as-is, never transformed into a guessed
    #: commercial GPU name.
    gpu_model: str | None = None

    # -- Display -------------------------------------------------------------
    resolution: str | None = None
    density_dpi: int | None = None
    refresh_rate_hz: float | None = None
    orientation: str | None = None
    #: Physical panel dimensions in pixels (``wm size`` Physical line).
    display_width_px: int | None = None
    display_height_px: int | None = None
    #: ``wm size`` override ("WxH") when the OEM sets one; None otherwise.
    display_override_resolution: str | None = None
    #: ``wm density`` override in dpi when set; None otherwise.
    display_override_density: int | None = None
    #: Surface orientation in degrees: 0 / 90 / 180 / 270 (the numeric form
    #: of ``orientation``, which keeps the human-readable label).
    display_orientation_degrees: int | None = None
    #: Distinct refresh rates the display advertises, ascending (Hz).
    supported_refresh_rates_hz: tuple[float, ...] | None = None
    # NOTE: only the PRIMARY display is reported. Secondary-display reads
    # are deferred to a later phase; sources are never silently mixed.

    # -- Storage -------------------------------------------------------------
    #: Internal shared storage (/data). Volumes are never silently combined.
    storage: StorageInfo | None = None
    #: Filesystem type of the primary internal volume (/data or
    #: /data/user/0) from /proc/mounts, e.g. "ext4", "f2fs".
    storage_filesystem: str | None = None

    # -- Identifiers (handled carefully; usually restricted) -----------------
    android_id: str | None = None
    wifi_mac: str | None = None
    bluetooth_mac: str | None = None