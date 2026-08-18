"""Canonical semantic thresholds for dashboard metrics.

This is the single authoritative source for threshold values and their
classification functions. ``gui/thresholds.py`` re-exports it (adding the
Qt-dependent ``apply_metric_level`` helper) and the diagnostics engine
derives its severity thresholds from it — values are never restated in
two places with independent lifecycles.

All threshold values live here as named constants — never as magic
numbers scattered through widgets — and every classification is a pure
function that returns a :class:`MetricLevel`.

Terminology is deliberately conservative (Normal / Elevated / High): the
values are presentation heuristics, not medical or safety claims, and no
device specification is cited for them.
"""

from __future__ import annotations

from enum import Enum


class MetricLevel(Enum):
    """Presentation level of a metric value."""

    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"


#: CPU utilization above this percent is shown as Elevated (amber).
CPU_ELEVATED_PERCENT = 60.0
#: CPU utilization at/above this percent is shown as High (red).
CPU_HIGH_PERCENT = 85.0

#: Used share of total memory above this percent is Elevated (amber).
MEMORY_USED_ELEVATED_PERCENT = 70.0
#: Used share of total memory at/above this percent is High (red).
MEMORY_USED_HIGH_PERCENT = 90.0

#: Battery temperature above this °C is Elevated (amber).
TEMPERATURE_ELEVATED_C = 40.0
#: Battery temperature at/above this °C is High (red).
TEMPERATURE_HIGH_C = 45.0

#: Used share of the internal storage volume above this percent is
#: Elevated (amber) — operationally significant pressure starts around here.
STORAGE_USED_ELEVATED_PERCENT = 80.0
#: Used share of the internal storage volume at/above this percent is High
#: (red) — the widely recognized "storage running out" region.
STORAGE_USED_HIGH_PERCENT = 90.0

#: Battery level below this percent is Elevated (amber) — the low-battery
#: region where the user should consider charging.
BATTERY_LEVEL_ELEVATED_PERCENT = 35.0
#: Battery level at/below this percent is High (red) — the critically-low
#: region where the device may shut down soon.
BATTERY_LEVEL_HIGH_PERCENT = 20.0


def classify_cpu(utilization_percent: float | None) -> MetricLevel:
    """Classify aggregate/core CPU utilization."""
    if utilization_percent is None:
        return MetricLevel.NORMAL
    if utilization_percent >= CPU_HIGH_PERCENT:
        return MetricLevel.HIGH
    if utilization_percent > CPU_ELEVATED_PERCENT:
        return MetricLevel.ELEVATED
    return MetricLevel.NORMAL


def classify_used_memory(used_percent: float | None) -> MetricLevel:
    """Classify the used share of total memory."""
    if used_percent is None:
        return MetricLevel.NORMAL
    if used_percent >= MEMORY_USED_HIGH_PERCENT:
        return MetricLevel.HIGH
    if used_percent > MEMORY_USED_ELEVATED_PERCENT:
        return MetricLevel.ELEVATED
    return MetricLevel.NORMAL


def classify_temperature(celsius: float | None) -> MetricLevel:
    """Classify battery temperature in degrees Celsius."""
    if celsius is None:
        return MetricLevel.NORMAL
    if celsius >= TEMPERATURE_HIGH_C:
        return MetricLevel.HIGH
    if celsius > TEMPERATURE_ELEVATED_C:
        return MetricLevel.ELEVATED
    return MetricLevel.NORMAL


def classify_storage(used_percent: float | None) -> MetricLevel:
    """Classify the used share of the internal storage volume."""
    if used_percent is None:
        return MetricLevel.NORMAL
    if used_percent >= STORAGE_USED_HIGH_PERCENT:
        return MetricLevel.HIGH
    if used_percent > STORAGE_USED_ELEVATED_PERCENT:
        return MetricLevel.ELEVATED
    return MetricLevel.NORMAL


def classify_battery_level(level_percent: float | None) -> MetricLevel:
    """Classify the battery level; low levels are the risky direction.

    Unlike CPU/memory/storage (where *high* usage is the risk), a *low*
    battery level is the risk: below the elevated threshold is Elevated,
    at/below the high threshold is High.
    """
    if level_percent is None:
        return MetricLevel.NORMAL
    if level_percent <= BATTERY_LEVEL_HIGH_PERCENT:
        return MetricLevel.HIGH
    if level_percent < BATTERY_LEVEL_ELEVATED_PERCENT:
        return MetricLevel.ELEVATED
    return MetricLevel.NORMAL


__all__ = [
    "BATTERY_LEVEL_ELEVATED_PERCENT",
    "BATTERY_LEVEL_HIGH_PERCENT",
    "CPU_ELEVATED_PERCENT",
    "CPU_HIGH_PERCENT",
    "MEMORY_USED_ELEVATED_PERCENT",
    "MEMORY_USED_HIGH_PERCENT",
    "STORAGE_USED_ELEVATED_PERCENT",
    "STORAGE_USED_HIGH_PERCENT",
    "TEMPERATURE_ELEVATED_C",
    "TEMPERATURE_HIGH_C",
    "MetricLevel",
    "classify_battery_level",
    "classify_cpu",
    "classify_storage",
    "classify_temperature",
    "classify_used_memory",
]