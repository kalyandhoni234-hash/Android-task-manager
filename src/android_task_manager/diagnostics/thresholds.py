"""Diagnostics thresholds.

Shared values (CPU, memory, temperature) derive from the single canonical
source, ``android_task_manager.thresholds`` — the values are aliased here
under severity-oriented names (ELEVATED -> WARNING, HIGH/CRITICAL ->
CRITICAL) so rule code reads in the diagnostics severity vocabulary
without ever restating a value.

``STORAGE_*`` thresholds are new: no storage thresholds existed anywhere
in the codebase before the diagnostics layer. They are presentation
heuristics with the same conservative spirit as the existing ones —
terminology stays WARNING/CRITICAL, no device specification is cited.
"""

from __future__ import annotations

from ..thresholds import (
    CPU_ELEVATED_PERCENT as _CANONICAL_CPU_ELEVATED,
)
from ..thresholds import (
    CPU_HIGH_PERCENT as _CANONICAL_CPU_HIGH,
)
from ..thresholds import (
    MEMORY_USED_ELEVATED_PERCENT as _CANONICAL_MEMORY_ELEVATED,
)
from ..thresholds import (
    MEMORY_USED_HIGH_PERCENT as _CANONICAL_MEMORY_HIGH,
)
from ..thresholds import (
    STORAGE_USED_ELEVATED_PERCENT as _CANONICAL_STORAGE_ELEVATED,
)
from ..thresholds import (
    STORAGE_USED_HIGH_PERCENT as _CANONICAL_STORAGE_HIGH,
)
from ..thresholds import (
    TEMPERATURE_ELEVATED_C as _CANONICAL_TEMPERATURE_ELEVATED,
)
from ..thresholds import (
    TEMPERATURE_HIGH_C as _CANONICAL_TEMPERATURE_HIGH,
)

#: Aggregate CPU utilization above this percent is a WARNING.
CPU_ELEVATED_PERCENT = _CANONICAL_CPU_ELEVATED
#: Aggregate CPU utilization at/above this percent is CRITICAL.
CPU_CRITICAL_PERCENT = _CANONICAL_CPU_HIGH

#: Used share of total memory above this percent is a WARNING.
MEMORY_ELEVATED_PERCENT = _CANONICAL_MEMORY_ELEVATED
#: Used share of total memory at/above this percent is CRITICAL.
MEMORY_CRITICAL_PERCENT = _CANONICAL_MEMORY_HIGH

#: Battery temperature above this °C is a WARNING.
TEMPERATURE_ELEVATED_C = _CANONICAL_TEMPERATURE_ELEVATED
#: Battery temperature at/above this °C is CRITICAL.
TEMPERATURE_CRITICAL_C = _CANONICAL_TEMPERATURE_HIGH

#: Used share of the internal storage volume above this percent is a
#: WARNING (canonical source: the live-dashboard thresholds).
STORAGE_ELEVATED_PERCENT = _CANONICAL_STORAGE_ELEVATED
#: Used share of the internal storage volume at/above this percent is
#: CRITICAL (canonical source: the live-dashboard thresholds).
STORAGE_CRITICAL_PERCENT = _CANONICAL_STORAGE_HIGH


__all__ = [
    "CPU_CRITICAL_PERCENT",
    "CPU_ELEVATED_PERCENT",
    "MEMORY_CRITICAL_PERCENT",
    "MEMORY_ELEVATED_PERCENT",
    "STORAGE_CRITICAL_PERCENT",
    "STORAGE_ELEVATED_PERCENT",
    "TEMPERATURE_CRITICAL_C",
    "TEMPERATURE_ELEVATED_C",
]