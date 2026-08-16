"""GUI thresholds: re-export of the canonical core thresholds.

The authoritative values and classifiers live in
``android_task_manager.thresholds`` (single source of truth — widgets,
the diagnostics engine and this module all consume it). Only the
Qt-dependent presentation helper ``apply_metric_level`` lives here.
"""

from __future__ import annotations

from ..thresholds import (  # noqa: F401 - re-exported for existing callers
    CPU_ELEVATED_PERCENT,
    CPU_HIGH_PERCENT,
    MEMORY_USED_ELEVATED_PERCENT,
    MEMORY_USED_HIGH_PERCENT,
    TEMPERATURE_ELEVATED_C,
    TEMPERATURE_HIGH_C,
    MetricLevel,
    classify_cpu,
    classify_temperature,
    classify_used_memory,
)
from ..thresholds import __all__ as _CORE_ALL


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


__all__ = [*_CORE_ALL, "apply_metric_level"]