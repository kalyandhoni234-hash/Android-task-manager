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

from ..adb.connection import CommandRunner
from ..adb.exceptions import ADBError
from .models import DeviceInformation, StorageInfo
from .parser import (
    parse_android_id,
    parse_cpu_hardware_line,
    parse_df_k,
    parse_getprop_output,
    parse_mac_address,
    parse_max_frequency_khz,
    parse_orientation,
    parse_refresh_rate,
    parse_wm_density,
    parse_wm_size,
    pick_internal_storage,
)

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
    "bootloader": ("ro.boot.bootloader",),
    "baseband": (
        "ro.build.version.baseband",
        "gsm.version.baseband",
        "ro.boot.baseband",
    ),
    "architecture": ("ro.product.cpu.abi",),
}


class DeviceInfoCollector:
    """Collects one structured ``DeviceInformation`` snapshot per call."""

    def __init__(self, runner: CommandRunner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def sample(self) -> DeviceInformation:
        """Read the full identity snapshot (best-effort per field)."""
        text = self._runner.shell(["getprop"], timeout=self._timeout)
        props = parse_getprop_output(text)
        return DeviceInformation(
            **_property_fields(props),
            soc=_soc_name(props),
            kernel=self._read(
                lambda: _uname_kernel(self._runner.shell(["uname", "-r"], timeout=self._timeout))
            ),
            processor=_processor_name(
                props, self._read(lambda: parse_cpu_hardware_line(self._runner.shell(["cat", "/proc/cpuinfo"], timeout=self._timeout)))
            ),
            max_frequency_khz=self._read(
                lambda: parse_max_frequency_khz(
                    self._runner.shell(
                        ["cat", "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"],
                        timeout=self._timeout,
                    )
                )
            ),
            resolution=self._read(
                lambda: parse_wm_size(self._runner.shell(["wm", "size"], timeout=self._timeout))
            ),
            density_dpi=self._read(
                lambda: parse_wm_density(
                    self._runner.shell(["wm", "density"], timeout=self._timeout)
                )
            ),
            refresh_rate_hz=self._read(
                lambda: parse_refresh_rate(
                    self._runner.shell(["dumpsys", "display"], timeout=self._timeout)
                )
            ),
            orientation=self._read(
                lambda: parse_orientation(
                    self._runner.shell(["dumpsys", "input"], timeout=self._timeout)
                )
            ),
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


def _processor_name(props: dict[str, str], cpuinfo_hardware: str | None) -> str | None:
    """ro.soc.model when published, else the /proc/cpuinfo Hardware line."""
    model = props.get("ro.soc.model")
    if model and model.strip():
        return model.strip()
    return cpuinfo_hardware