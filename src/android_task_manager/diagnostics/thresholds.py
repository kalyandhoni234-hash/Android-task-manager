"""Diagnostics thresholds.

Values mirror the canonical presentation thresholds in
``gui/thresholds.py`` (CPU, memory, temperature): the diagnostics engine
is a pure core layer and must not import from the GUI package, so the
values are restated here with their documented meaning. A later phase may
unify the two modules when the GUI thresholds move into the core layer.

``STORAGE_*`` thresholds are new: no storage thresholds existed anywhere
in the codebase before the diagnostics layer. They are presentation
heuristics with the same conservative spirit as the existing ones —
terminology stays WARNING/CRITICAL, no device specification is cited.

Severity mapping (existing GUI levels -> diagnostics severities):

- ``_ELEVATED_`` thresholds -> WARNING
- ``_HIGH`` / ``_CRITICAL_`` thresholds -> CRITICAL
"""

from __future__ import annotations

#: Aggregate CPU utilization above this percent is a WARNING.
CPU_ELEVATED_PERCENT = 60.0
#: Aggregate CPU utilization at/above this percent is CRITICAL.
CPU_CRITICAL_PERCENT = 85.0

#: Used share of total memory above this percent is a WARNING.
MEMORY_ELEVATED_PERCENT = 70.0
#: Used share of total memory at/above this percent is CRITICAL.
MEMORY_CRITICAL_PERCENT = 90.0

#: Battery temperature above this °C is a WARNING.
TEMPERATURE_ELEVATED_C = 40.0
#: Battery temperature at/above this °C is CRITICAL.
TEMPERATURE_CRITICAL_C = 45.0

#: Used share of the internal storage volume above this percent is a
#: WARNING (operationally significant pressure starts around here).
STORAGE_ELEVATED_PERCENT = 80.0
#: Used share of the internal storage volume at/above this percent is
#: CRITICAL (the widely recognized "storage running out" region; low
#: free space breaks app updates and system operations).
STORAGE_CRITICAL_PERCENT = 90.0


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