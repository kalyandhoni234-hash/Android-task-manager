"""Normalized battery data models.

Raw Android enum numbers from ``dumpsys battery`` are kept alongside their
normalized human-readable enum so the renderer never shows raw numbers and
unknown OEM values are preserved instead of being dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BatteryStatus(Enum):
    """Android BatteryManager.BATTERY_STATUS_* values (raw, label)."""

    UNKNOWN = (1, "Unknown")
    CHARGING = (2, "Charging")
    DISCHARGING = (3, "Discharging")
    NOT_CHARGING = (4, "Not charging")
    FULL = (5, "Full")

    @property
    def raw(self) -> int:
        return self.value[0]

    @property
    def label(self) -> str:
        return self.value[1]


class BatteryHealth(Enum):
    """Android BatteryManager.BATTERY_HEALTH_* values (raw, label)."""

    UNKNOWN = (1, "Unknown")
    GOOD = (2, "Good")
    OVERHEAT = (3, "Overheat")
    DEAD = (4, "Dead")
    OVER_VOLTAGE = (5, "Over voltage")
    UNSPECIFIED_FAILURE = (6, "Unspecified failure")
    COLD = (7, "Cold")

    @property
    def raw(self) -> int:
        return self.value[0]

    @property
    def label(self) -> str:
        return self.value[1]


_STATUS_BY_RAW = {status.raw: status for status in BatteryStatus}
_HEALTH_BY_RAW = {health.raw: health for health in BatteryHealth}


def battery_status_from_raw(raw: int | None) -> BatteryStatus:
    """Map a raw status number to a BatteryStatus; unknown -> UNKNOWN."""
    if raw is None:
        return BatteryStatus.UNKNOWN
    return _STATUS_BY_RAW.get(raw, BatteryStatus.UNKNOWN)


def battery_health_from_raw(raw: int | None) -> BatteryHealth:
    """Map a raw health number to a BatteryHealth; unknown -> UNKNOWN."""
    if raw is None:
        return BatteryHealth.UNKNOWN
    return _HEALTH_BY_RAW.get(raw, BatteryHealth.UNKNOWN)


@dataclass(frozen=True)
class BatterySnapshot:
    """A normalized view of the device battery at one moment."""

    #: Monotonic timestamp of the sample.
    timestamp: float
    #: Computed as level / scale * 100, clamped to [0, 100]; None when the
    #: scale is invalid. See ``level_percent`` documentation in parser.
    level_percent: float | None
    #: The scale reported by the device (100 on stock Android; do not assume).
    scale: int | None
    #: Voltage in millivolts (raw device precision preserved).
    voltage_mv: int | None
    #: Temperature in degrees Celsius (device reports 0.1 °C units).
    temperature_c: float | None
    #: Normalized charging state.
    status: BatteryStatus
    #: Raw Android status enum value (for debugging / unknown values).
    status_raw: int | None
    #: Normalized health state.
    health: BatteryHealth
    #: Raw Android health enum value (for debugging / unknown values).
    health_raw: int | None
    #: Whether a battery is physically present.
    present: bool | None
    ac_powered: bool | None
    usb_powered: bool | None
    wireless_powered: bool | None
    #: Battery technology string, e.g. "Li-poly" ("" when unreported).
    technology: str
    #: Raw charge counter value as reported by the device (unit is device/OEM
    #: specific; kept verbatim, no unit conversion claimed).
    charge_counter: int | None