"""Parsing of Linux ``/proc/meminfo`` text into normalized integer KiB.

Values are order-independent, unknown/additional fields are tolerated, and any
required field that is missing or malformed raises a controlled
``MemoryParseError`` rather than producing silently-wrong numbers.
"""

from __future__ import annotations

from typing import Mapping

#: Maps the raw /proc/meminfo field name to the normalized snapshot attribute.
_FIELD_MAP: dict[str, str] = {
    "MemTotal": "total_kb",
    "MemFree": "free_kb",
    "MemAvailable": "available_kb",
    "Buffers": "buffers_kb",
    "Cached": "cached_kb",
    "SwapCached": "swap_cached_kb",
}
_REQUIRED = set(_FIELD_MAP.values())


class MemoryParseError(ValueError):
    """Raised when required /proc/meminfo fields are missing or invalid."""


def parse_meminfo(text: str) -> dict[str, int]:
    """Parse /proc/meminfo text into a dict of normalized integer KiB values.

    Returns keys matching MemorySnapshot field names. Raises MemoryParseError
    if any required field is absent or holds a non-integer value.
    """
    values: dict[str, int] = {}

    for raw_line in text.splitlines():
        if ":" not in raw_line:
            continue
        name, _, rest = raw_line.partition(":")
        name = name.strip()
        if name not in _FIELD_MAP:
            continue  # tolerate unknown/additional fields

        tokens = rest.strip().split()
        if not tokens:
            raise MemoryParseError(
                f"Field {name!r} is missing a value in /proc/meminfo."
            )
        try:
            value = int(tokens[0])
        except ValueError as exc:
            raise MemoryParseError(
                f"Field {name!r} has a non-integer value {tokens[0]!r} in /proc/meminfo."
            ) from exc
        values[_FIELD_MAP[name]] = value

    missing = _REQUIRED - set(values)
    if missing:
        raise MemoryParseError(
            "Missing required field(s) in /proc/meminfo: "
            + ", ".join(sorted(missing))
        )
    return values