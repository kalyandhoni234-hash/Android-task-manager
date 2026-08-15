"""Documented semantic thresholds for dashboard metrics.

All threshold values live here as named constants — never as magic numbers
scattered through widgets — and every classification is a pure function
that returns a :class:`MetricLevel`.

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


def apply_metric_level(label, level: MetricLevel) -> None:
    """Set the ``level`` dynamic property so the stylesheet colors the label.

    The base objectName (e.g. ``valueBig``) is preserved — only the color
    changes — so the property composes with existing typography rules.
    """
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415 - lazy Qt import

    label.setProperty("level", level.value)
    app = QApplication.instance()
    if app is not None:
        app.style().unpolish(label)
        app.style().polish(label)


__all__ = [
    "CPU_ELEVATED_PERCENT",
    "CPU_HIGH_PERCENT",
    "MEMORY_USED_ELEVATED_PERCENT",
    "MEMORY_USED_HIGH_PERCENT",
    "TEMPERATURE_ELEVATED_C",
    "TEMPERATURE_HIGH_C",
    "MetricLevel",
    "apply_metric_level",
    "classify_cpu",
    "classify_temperature",
    "classify_used_memory",
]
