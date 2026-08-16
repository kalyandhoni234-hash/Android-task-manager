"""Device-information collector: one structured read of the device identity.

Runs once per connection session (not per sampling tick) through the shared
``CommandRunner`` — the same ADB facade every other collector uses; this
module never touches ``subprocess``. A bulk ``getprop`` read supplies the
system properties; ``wm`` / ``df`` / ``dumpsys`` / sysfs reads supply
display, storage and identifier facts.

Rules:

- The bulk property read is the first command; if it fails the device is
  not usable, so the error propagates to the monitor's connection handling.
- Every subsequent read is individually best-effort: a failure marks that
  field unavailable (None) and never aborts the rest of the snapshot.
- No values are inferred, looked up, or hardcoded for any device.
"""

from __future__ import annotations

from datetime import datetime

from ..adb.connection import CommandRunner
from ..adb.exceptions import ADBError
from .models import DeviceInformation, StorageInfo
from .parser import (
    derive_boot_time,
    derive_cpu_64bit,
    khz_to_hz,
    parse_android_id,
    parse_charge_full_design,
    parse_cpu_features,
    parse_cpu_hardware_line,
    parse_cpu_range,
    parse_cpufreq_khz,
    parse_cpuinfo_cores,
    parse_cpuinfo_model_name,
    parse_cycle_count,
    parse_df_k,
    parse_epoch_seconds,
    parse_getprop_output,
    parse_governor,
    parse_gpu_gles,
    parse_mac_address,
    parse_max_frequency_khz,
    parse_mounts_filesystem,
    parse_orientation,
    parse_orientation_degrees,
    parse_proc_uptime,
    parse_refresh_rate,
    parse_supported_refresh_rates,
    parse_uname_a,
    parse_uname_a_machine,
    parse_wm_density,
    parse_wm_override_density,
    parse_wm_override_size,
    parse_wm_size,
    parse_wm_size_dimensions,
    pick_internal_storage,
)

#: Core-0 cpufreq directory; the representative policy/hardware node used for
#: the static CPU snapshot. Per-core dynamic reads stay in the cpu monitor.
_CPU0_CPUFREQ = "/sys/devices/system/cpu/cpu0/cpufreq"

#: Property keys consulted from the bulk ``getprop`` output, grouped by the
#: model field they feed. Keys absent from the output become None.
_PROPERTY_KEYS = {
    "manufacturer": ("ro.product.manufacturer",),
    "brand": ("ro.product.brand",),
    "model": ("ro.product.model",),
    "device": ("ro.product.device",),
    "product": ("ro.product.name",),
    "board": ("ro.product.board",),
    "hardware": ("ro.hardware",),
    "android_version": ("ro.build.version.release",),
    "api_level": ("ro.build.version.sdk",),
    "security_patch": (
        "ro.build.version.security_patch",
        "ro.vendor.build.security_patch",
    ),
    "build_id": ("ro.build.id",),
    "build_number": ("ro.build.display.id", "ro.build.version.incremental"),
    "build_fingerprint": ("ro.build.fingerprint",),
    "build_tags": ("ro.build.tags",),
    "build_type": ("ro.build.type",),
    "bootloader": ("ro.boot.bootloader",),
    "baseband": (
        "ro.build.version.baseband",
        "gsm.version.baseband",
        "ro.boot.baseband",
    ),
    "architecture": ("ro.product.cpu.abi",),
}

#: System facts read as whole commands rather than properties. Every read is
#: individually best-effort; a failure marks only that field unavailable.
#:     kernel         <- uname -r
#:     kernel_version <- uname -a
#:     uptime_seconds <- cat /proc/uptime  (first token, fractional seconds)
#:     boot_time      <- date +%s (device clock) − uptime; DERIVED estimate,
#:                       produced only when the derivation is reliable.
#:     gpu_vendor / gpu_model
#:                    <- dumpsys SurfaceFlinger (GLES line); only the PRIMARY
#:                       display/GPU is reported, never a guessed model.
#:     display facts  <- wm size / wm density / dumpsys display / dumpsys
#:                       input; each command is read once per snapshot and
#:                       parsed into several fields (never re-read per field).
#:     battery_design_capacity / battery_cycle_count
#:                    <- /sys/class/power_supply/battery/{charge_full_design,
#:                       cycle_count}; STATIC facts only — dynamic battery
#:                       data belongs to the live battery monitor.
#:     storage_filesystem
#:                    <- cat /proc/mounts (fs type of the /data mount).


class DeviceInfoCollector:
    """Collects one structured ``DeviceInformation`` snapshot per call."""

    def __init__(self, runner: CommandRunner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def sample(self) -> DeviceInformation:
        """Read the full identity snapshot (best-effort per field)."""
        text = self._runner.shell(["getprop"], timeout=self._timeout)
        props = parse_getprop_output(text)
        uptime_seconds = self._read(
            lambda: parse_proc_uptime(
                self._runner.shell(["cat", "/proc/uptime"], timeout=self._timeout)
            )
        )
        uname_text = self._read(
            lambda: self._runner.shell(["uname", "-a"], timeout=self._timeout)
        )
        cpuinfo_text = self._read(
            lambda: self._runner.shell(["cat", "/proc/cpuinfo"], timeout=self._timeout)
        )
        machine = parse_uname_a_machine(uname_text) if uname_text is not None else None
        core_count = self._sample_core_count(cpuinfo_text)
        online_cores = self._read(
            lambda: parse_cpu_range(
                self._runner.shell(
                    ["cat", "/sys/devices/system/cpu/online"], timeout=self._timeout
                )
            )
        )
        current_hz, min_hz, max_hz, governor = self._sample_cpufreq()
        wm_size_text = self._read(
            lambda: self._runner.shell(["wm", "size"], timeout=self._timeout)
        )
        wm_density_text = self._read(
            lambda: self._runner.shell(["wm", "density"], timeout=self._timeout)
        )
        display_text = self._read(
            lambda: self._runner.shell(["dumpsys", "display"], timeout=self._timeout)
        )
        input_text = self._read(
            lambda: self._runner.shell(["dumpsys", "input"], timeout=self._timeout)
        )
        surfaceflinger_text = self._read(
            lambda: self._runner.shell(["dumpsys", "SurfaceFlinger"], timeout=self._timeout)
        )
        dimensions = (
            parse_wm_size_dimensions(wm_size_text) if wm_size_text is not None else None
        )
        gpu_vendor, gpu_model = (
            parse_gpu_gles(surfaceflinger_text)
            if surfaceflinger_text is not None
            else (None, None)
        )
        battery_design_capacity = self._read(
            lambda: parse_charge_full_design(
                self._runner.shell(
                    ["cat", "/sys/class/power_supply/battery/charge_full_design"],
                    timeout=self._timeout,
                )
            )
        )
        battery_cycle_count = self._read(
            lambda: parse_cycle_count(
                self._runner.shell(
                    ["cat", "/sys/class/power_supply/battery/cycle_count"],
                    timeout=self._timeout,
                )
            )
        )
        mounts_text = self._read(
            lambda: self._runner.shell(["cat", "/proc/mounts"], timeout=self._timeout)
        )
        storage_filesystem = (
            parse_mounts_filesystem(mounts_text, ("/data", "/data/user/0"))
            if mounts_text is not None
            else None
        )
        return DeviceInformation(
            **_property_fields(props),
            soc=_soc_name(props),
            cpu_abis=_cpu_abis(props),
            kernel=self._read(
                lambda: _uname_kernel(self._runner.shell(["uname", "-r"], timeout=self._timeout))
            ),
            kernel_version=parse_uname_a(uname_text) if uname_text is not None else None,
            cpu_architecture=machine,
            cpu_64bit=derive_cpu_64bit(machine),
            uptime_seconds=uptime_seconds,
            boot_time=self._sample_boot_time(uptime_seconds),
            processor=_processor_name(
                props,
                parse_cpu_hardware_line(cpuinfo_text) if cpuinfo_text is not None else None,
                parse_cpuinfo_model_name(cpuinfo_text) if cpuinfo_text is not None else None,
            ),
            cpu_core_count=core_count,
            cpu_online_cores=online_cores,
            cpu_offline_cores=_derive_offline_cores(core_count, online_cores),
            cpu_governor=governor,
            cpu_current_frequency_hz=current_hz,
            cpu_min_frequency_hz=min_hz,
            cpu_max_frequency_hz=max_hz,
            cpu_features=(
                parse_cpu_features(cpuinfo_text) if cpuinfo_text is not None else None
            ),
            max_frequency_khz=self._read(
                lambda: parse_max_frequency_khz(
                    self._runner.shell(
                        ["cat", "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"],
                        timeout=self._timeout,
                    )
                )
            ),
            resolution=(
                parse_wm_size(wm_size_text) if wm_size_text is not None else None
            ),
            density_dpi=(
                parse_wm_density(wm_density_text) if wm_density_text is not None else None
            ),
            refresh_rate_hz=(
                parse_refresh_rate(display_text) if display_text is not None else None
            ),
            orientation=(
                parse_orientation(input_text) if input_text is not None else None
            ),
            display_width_px=dimensions[0] if dimensions is not None else None,
            display_height_px=dimensions[1] if dimensions is not None else None,
            display_override_resolution=(
                parse_wm_override_size(wm_size_text)
                if wm_size_text is not None
                else None
            ),
            display_override_density=(
                parse_wm_override_density(wm_density_text)
                if wm_density_text is not None
                else None
            ),
            display_orientation_degrees=(
                parse_orientation_degrees(input_text) if input_text is not None else None
            ),
            supported_refresh_rates_hz=(
                parse_supported_refresh_rates(display_text)
                if display_text is not None
                else None
            ),
            gpu_vendor=gpu_vendor,
            gpu_model=gpu_model,
            battery_design_capacity=battery_design_capacity,
            battery_cycle_count=battery_cycle_count,
            storage_filesystem=storage_filesystem,
            storage=self._read(self._sample_storage),
            android_id=self._read(
                lambda: parse_android_id(
                    self._runner.shell(
                        ["settings", "get", "secure", "android_id"], timeout=self._timeout
                    )
                )
            ),
            wifi_mac=self._read(
                lambda: parse_mac_address(
                    self._runner.shell(
                        ["cat", "/sys/class/net/wlan0/address"], timeout=self._timeout
                    )
                )
            ),
            bluetooth_mac=self._read(
                lambda: parse_mac_address(
                    self._runner.shell(
                        ["settings", "get", "secure", "bluetooth_address"],
                        timeout=self._timeout,
                    )
                )
            ),
        )

    # ------------------------------------------------------------------
    # Best-effort helpers
    # ------------------------------------------------------------------

    def _read(self, reader):
        """Run one optional read; failures and malformed output -> None."""
        try:
            return reader()
        except ADBError:
            return None

    def _sample_storage(self) -> StorageInfo | None:
        volumes = parse_df_k(self._runner.shell(["df", "-k", "/data"], timeout=self._timeout))
        return pick_internal_storage(volumes)

    def _sample_boot_time(self, uptime_seconds: float | None) -> datetime | None:
        """Derived boot time (device clock − uptime); None when unreliable."""
        if uptime_seconds is None:
            return None
        device_epoch = self._read(
            lambda: parse_epoch_seconds(
                self._runner.shell(["date", "+%s"], timeout=self._timeout)
            )
        )
        if device_epoch is None:
            return None
        return derive_boot_time(device_epoch, uptime_seconds)

    def _sample_core_count(self, cpuinfo_text: str | None) -> int | None:
        """Total logical cores: /sys present range, then /proc/cpuinfo."""
        present = self._read(
            lambda: parse_cpu_range(
                self._runner.shell(
                    ["cat", "/sys/devices/system/cpu/present"], timeout=self._timeout
                )
            )
        )
        if present is not None:
            return present
        if cpuinfo_text is None:
            return None
        return parse_cpuinfo_cores(cpuinfo_text)

    def _sample_cpufreq(
        self,
    ) -> tuple[float | None, float | None, float | None, str | None]:
        """Core-0 scaling frequencies (Hz) and governor; each best-effort."""
        base = _CPU0_CPUFREQ
        current_khz = self._read(
            lambda: parse_cpufreq_khz(
                self._runner.shell(["cat", f"{base}/scaling_cur_freq"], timeout=self._timeout)
            )
        )
        min_khz = self._read(
            lambda: parse_cpufreq_khz(
                self._runner.shell(["cat", f"{base}/scaling_min_freq"], timeout=self._timeout)
            )
        )
        max_khz = self._read(
            lambda: parse_cpufreq_khz(
                self._runner.shell(["cat", f"{base}/scaling_max_freq"], timeout=self._timeout)
            )
        )
        governor = self._read(
            lambda: parse_governor(
                self._runner.shell(["cat", f"{base}/scaling_governor"], timeout=self._timeout)
            )
        )
        return (
            khz_to_hz(current_khz) if current_khz is not None else None,
            khz_to_hz(min_khz) if min_khz is not None else None,
            khz_to_hz(max_khz) if max_khz is not None else None,
            governor,
        )


def _property_fields(props: dict[str, str]) -> dict[str, str | None]:
    """First-present property per model field, normalized to None."""
    fields: dict[str, str | None] = {}
    for field, keys in _PROPERTY_KEYS.items():
        value = next((props.get(key) for key in keys if props.get(key) is not None), None)
        fields[field] = value.strip() if value is not None and value.strip() else None
    return fields


def _uname_kernel(text: str) -> str | None:
    """The kernel release string from ``uname -r`` (empty -> None)."""
    value = text.strip()
    return value or None


def _soc_name(props: dict[str, str]) -> str | None:
    """A human SoC name from ro.soc.*, falling back to the platform token."""
    manufacturer = props.get("ro.soc.manufacturer")
    model = props.get("ro.soc.model")
    if manufacturer and model:
        return f"{manufacturer} {model}".strip()
    if model:
        return model
    return props.get("ro.board.platform") or None


def _processor_name(
    props: dict[str, str],
    cpuinfo_hardware: str | None,
    cpuinfo_model: str | None,
) -> str | None:
    """ro.soc.model when published, else the /proc/cpuinfo Hardware line,
    else the cpuinfo ``model name`` line."""
    model = props.get("ro.soc.model")
    if model and model.strip():
        return model.strip()
    if cpuinfo_hardware:
        return cpuinfo_hardware
    return cpuinfo_model


def _cpu_abis(props: dict[str, str]) -> tuple[str, ...] | None:
    """Supported ABIs from ro.product.cpu.abilist, in order, de-duplicated."""
    raw = props.get("ro.product.cpu.abilist")
    if raw is None:
        return None
    abis: list[str] = []
    for part in raw.split(","):
        abi = part.strip()
        if abi and abi not in abis:
            abis.append(abi)
    return tuple(abis) or None


def _derive_offline_cores(
    core_count: int | None, online_cores: int | None
) -> int | None:
    """Offline cores as ``core_count − online`` when both are consistent."""
    if core_count is None or online_cores is None:
        return None
    if online_cores > core_count:
        return None
    return core_count - online_cores