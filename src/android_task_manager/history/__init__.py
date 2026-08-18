"""Historical metrics: bounded per-metric windows with statistics.

Pure and deterministic — no ADB, no GUI. The GUI feeds it from the monitor
snapshots; the rule engine reads it for sustained-condition evaluation.
"""

from .metrics import (
    MetricHistory,
    MetricStats,
    PeakPeriod,
    Sample,
    TrendDirection,
)
from .session import (
    BATTERY_MAX_SAMPLES,
    CPU_MAX_SAMPLES,
    MEMORY_MAX_SAMPLES,
    METRIC_BATTERY,
    METRIC_CPU,
    METRIC_MEMORY,
    METRIC_STORAGE,
    STORAGE_MAX_SAMPLES,
    SessionHistory,
    SessionStats,
)

__all__ = [
    "BATTERY_MAX_SAMPLES",
    "CPU_MAX_SAMPLES",
    "MEMORY_MAX_SAMPLES",
    "METRIC_BATTERY",
    "METRIC_CPU",
    "METRIC_MEMORY",
    "METRIC_STORAGE",
    "STORAGE_MAX_SAMPLES",
    "MetricHistory",
    "MetricStats",
    "PeakPeriod",
    "Sample",
    "SessionHistory",
    "SessionStats",
    "TrendDirection",
]
