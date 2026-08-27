"""Parsing of ``dumpsys battery`` output into a normalized BatterySnapshot.

The parser is key/value based: it tolerates any field order, additional/unknown
fields and blank lines. Required fields must be present and well-formed
(otherwise BatteryParseError); optional fields are silently defaulted when
absent or malformed. Raw Android status/health enum numbers are preserved and
normalized with documented mappings.
"""

from __future__ import annotations

from .models import (
    BatterySnapshot,
    battery_health_from_raw,
    battery_status_from_raw,
)

#: Fields that must exist and parse cleanly in dumpsys battery output.
_REQUIRED = {
    "AC powered",
    "USB powered",
    "Wireless powered",
    "status",
    "health",
    "present",
    "level",
    "scale",
    "voltage",
    "temperature",
}

#: Optional int-typed fields (tolerated if absent or unparseable).
_OPTIONAL_INT_FIELDS = {"Charge counter"}

#: Optional string fields.
_OPTIONAL_STR_FIELDS = {"technology"}


class BatteryParseError(ValueError):
    """Raised when required dumpsys battery data is missing or invalid."""


def parse_battery_output(text: str, timestamp: float = 0.0) -> BatterySnapshot:
    """Parse dumpsys battery text into a BatterySnapshot.

    ``timestamp`` is supplied by the collector (monotonic clock) and attached
    here so the snapshot is created complete and frozen.
    """
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue  # header ("Current Battery Service state:") / blank lines
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()

    missing = _REQUIRED - set(fields)
    if missing:
        raise BatteryParseError(
            "Missing required field(s) in dumpsys battery output: "
            + ", ".join(sorted(missing))
        )

    ac_powered = _parse_bool(fields["AC powered"], "AC powered")
    usb_powered = _parse_bool(fields["USB powered"], "USB powered")
    wireless_powered = _parse_bool(fields["Wireless powered"], "Wireless powered")
    status_raw = _parse_int(fields["status"], "status")
    health_raw = _parse_int(fields["health"], "health")
    present = _parse_bool(fields["present"], "present")
    level = _parse_int(fields["level"], "level")
    scale = _parse_int(fields["scale"], "scale")
    voltage_mv = _parse_int_range(
        fields["voltage"], "voltage", 2500, 6000, unit="mV"
    )
    temperature_raw = _parse_int_range(
        fields["temperature"], "temperature", -300, 800, unit="0.1°C"
    )

    return BatterySnapshot(
        timestamp=timestamp,
        level_percent=_level_percent(level, scale),
        scale=scale,
        voltage_mv=voltage_mv,
        # device reports temperature in 0.1 °C units (341 -> 34.1 °C)
        temperature_c=temperature_raw / 10.0,
        status=battery_status_from_raw(status_raw),
        status_raw=status_raw,
        health=battery_health_from_raw(health_raw),
        health_raw=health_raw,
        present=present,
        ac_powered=ac_powered,
        usb_powered=usb_powered,
        wireless_powered=wireless_powered,
        technology=_optional_str(fields, "technology"),
        charge_counter=_optional_int(fields, "Charge counter"),
    )


def _parse_int(value: str, field: str) -> int:
    try:
        return int(value.strip())
    except ValueError as exc:
        raise BatteryParseError(
            f"Field {field!r} has invalid integer value {value!r}."
        ) from exc


def _parse_int_range(
    value: str, field: str, lo: int, hi: int, *, unit: str = ""
) -> int:
    """Parse an integer and reject values outside [lo, hi].

    Physical/domain justification for the range is documented at each
    call site.  ``unit`` is included in the error message for clarity.
    """
    raw = _parse_int(value, field)
    if raw < lo or raw > hi:
        msg = f"Field {field!r} value {raw} is outside plausible range [{lo}, {hi}]"
        if unit:
            msg += f" {unit}"
        raise BatteryParseError(msg)
    return raw


def _parse_bool(value: str, field: str) -> bool:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise BatteryParseError(
        f"Field {field!r} has invalid boolean value {value!r}."
    )


def _optional_int(fields: dict[str, str], key: str) -> int | None:
    if key not in fields:
        return None
    try:
        return int(fields[key])
    except ValueError:
        # Optional metric malformed or weirdly formatted — do not crash.
        return None


def _optional_str(fields: dict[str, str], key: str) -> str:
    return fields.get(key, "").strip()


def _level_percent(level: int, scale: int) -> float | None:
    """Compute level/scale*100, clamped to [0, 100].

    A non-positive scale would produce garbage, so it yields None (level is
    unknown) rather than a fabricated percentage. Clamping happens here, at
    the model boundary, to absorb OEMs reporting slightly out-of-range values.
    """
    if scale <= 0:
        return None
    percent = level / scale * 100.0
    return min(100.0, max(0.0, percent))