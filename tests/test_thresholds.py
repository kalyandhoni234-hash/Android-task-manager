"""Unit tests for the canonical thresholds and their diagnostics aliases.

Covers every classifier's boundary semantics (inclusive/exclusive) and
verifies the diagnostics layer aliases the canonical values — a value must
never live in two independent places with different lifecycles.
"""

from __future__ import annotations

from android_task_manager import thresholds as canonical
from android_task_manager.diagnostics import thresholds as diagnostics
from android_task_manager.thresholds import (
    MetricLevel,
    classify_battery_level,
    classify_cpu,
    classify_storage,
    classify_used_memory,
)

# ---------------------------------------------------------------------------
# classify_cpu
# ---------------------------------------------------------------------------


def test_cpu_none_is_normal() -> None:
    assert classify_cpu(None) is MetricLevel.NORMAL


def test_cpu_below_elevated_is_normal() -> None:
    assert classify_cpu(59.9) is MetricLevel.NORMAL


def test_cpu_elevated_is_strictly_above_threshold() -> None:
    assert classify_cpu(canonical.CPU_ELEVATED_PERCENT) is MetricLevel.NORMAL
    assert classify_cpu(60.1) is MetricLevel.ELEVATED


def test_cpu_high_is_inclusive() -> None:
    assert classify_cpu(canonical.CPU_HIGH_PERCENT) is MetricLevel.HIGH
    assert classify_cpu(99.9) is MetricLevel.HIGH


# ---------------------------------------------------------------------------
# classify_used_memory
# ---------------------------------------------------------------------------


def test_memory_none_is_normal() -> None:
    assert classify_used_memory(None) is MetricLevel.NORMAL


def test_memory_boundaries() -> None:
    assert classify_used_memory(69.9) is MetricLevel.NORMAL
    assert classify_used_memory(canonical.MEMORY_USED_ELEVATED_PERCENT) is MetricLevel.NORMAL
    assert classify_used_memory(70.1) is MetricLevel.ELEVATED
    assert classify_used_memory(canonical.MEMORY_USED_HIGH_PERCENT) is MetricLevel.HIGH


# ---------------------------------------------------------------------------
# classify_storage
# ---------------------------------------------------------------------------


def test_storage_none_is_normal() -> None:
    assert classify_storage(None) is MetricLevel.NORMAL


def test_storage_boundaries() -> None:
    assert classify_storage(79.9) is MetricLevel.NORMAL
    assert classify_storage(canonical.STORAGE_USED_ELEVATED_PERCENT) is MetricLevel.NORMAL
    assert classify_storage(80.1) is MetricLevel.ELEVATED
    assert classify_storage(canonical.STORAGE_USED_HIGH_PERCENT) is MetricLevel.HIGH
    assert classify_storage(100.0) is MetricLevel.HIGH


# ---------------------------------------------------------------------------
# classify_battery_level (low levels are the risk direction)
# ---------------------------------------------------------------------------


def test_battery_none_is_normal() -> None:
    assert classify_battery_level(None) is MetricLevel.NORMAL


def test_battery_full_is_normal() -> None:
    assert classify_battery_level(100.0) is MetricLevel.NORMAL
    assert classify_battery_level(36.0) is MetricLevel.NORMAL


def test_battery_elevated_is_below_threshold() -> None:
    assert classify_battery_level(canonical.BATTERY_LEVEL_ELEVATED_PERCENT) is MetricLevel.NORMAL
    assert classify_battery_level(34.9) is MetricLevel.ELEVATED


def test_battery_high_is_inclusive_and_dominant() -> None:
    assert classify_battery_level(canonical.BATTERY_LEVEL_HIGH_PERCENT) is MetricLevel.HIGH
    assert classify_battery_level(5.0) is MetricLevel.HIGH


# ---------------------------------------------------------------------------
# Diagnostics aliasing (single source of truth)
# ---------------------------------------------------------------------------


def test_diagnostics_storage_aliases_canonical_values() -> None:
    assert diagnostics.STORAGE_ELEVATED_PERCENT == canonical.STORAGE_USED_ELEVATED_PERCENT
    assert diagnostics.STORAGE_CRITICAL_PERCENT == canonical.STORAGE_USED_HIGH_PERCENT


def test_diagnostics_shared_aliases_canonical_values() -> None:
    assert diagnostics.CPU_ELEVATED_PERCENT == canonical.CPU_ELEVATED_PERCENT
    assert diagnostics.CPU_CRITICAL_PERCENT == canonical.CPU_HIGH_PERCENT
    assert diagnostics.MEMORY_ELEVATED_PERCENT == canonical.MEMORY_USED_ELEVATED_PERCENT
    assert diagnostics.MEMORY_CRITICAL_PERCENT == canonical.MEMORY_USED_HIGH_PERCENT
    assert diagnostics.TEMPERATURE_ELEVATED_C == canonical.TEMPERATURE_ELEVATED_C
    assert diagnostics.TEMPERATURE_CRITICAL_C == canonical.TEMPERATURE_HIGH_C