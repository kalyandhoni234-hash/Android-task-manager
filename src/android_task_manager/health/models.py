"""Unified device health model: components, findings and overall health.

The health engine is pure and deterministic. It consumes the normalized
live snapshots (CPU, memory, battery, storage, processes, applications,
network), classifies each component with the canonical thresholds from
:mod:`android_task_manager.thresholds` (never duplicated), and produces:

* per-component status (HEALTHY / WARNING / CRITICAL / UNAVAILABLE) plus a
  deterministic score (100 / 70 / 40; unavailable components are excluded,
  never scored as "healthy"),
* structured findings (severity, component, title, explanation, evidence,
  recommendation, timestamp),
* an overall score (the mean of the available component scores) and an
  overall status that reflects the most severe component — a critical
  component can never be hidden by a good average.

Unavailable data produces an UNAVAILABLE component and **no findings**: a
missing snapshot is never evidence of a problem (and never proof of
health). No value is fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class HealthStatus(Enum):
    """Deterministic health state of a component or the whole device."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNAVAILABLE = "unavailable"


class HealthSeverity(Enum):
    """Severity of a health finding."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


#: Component keys (stable identifiers used across the engine and GUI).
COMPONENT_CPU = "cpu"
COMPONENT_MEMORY = "memory"
COMPONENT_BATTERY = "battery"
COMPONENT_STORAGE = "storage"
COMPONENT_PROCESSES = "processes"
COMPONENT_APPLICATIONS = "applications"
COMPONENT_CONNECTIVITY = "connectivity"

_ALL_COMPONENTS = (
    COMPONENT_CPU,
    COMPONENT_MEMORY,
    COMPONENT_BATTERY,
    COMPONENT_STORAGE,
    COMPONENT_PROCESSES,
    COMPONENT_APPLICATIONS,
    COMPONENT_CONNECTIVITY,
)

#: Score per status: deterministic and explainable (mean of component
#: scores; unavailable components never participate).
_SCORES = {
    HealthStatus.HEALTHY: 100,
    HealthStatus.WARNING: 70,
    HealthStatus.CRITICAL: 40,
    HealthStatus.UNAVAILABLE: 0,
}

#: Overall-status boundaries on the mean score (only meaningful when at
#: least one component is available).
_OVERALL_HEALTHY_MIN = 90.0
_OVERALL_WARNING_MIN = 60.0


@dataclass(frozen=True)
class Finding:
    """A structured, evidence-backed health finding."""

    severity: HealthSeverity
    component: str
    title: str
    explanation: str
    evidence: str
    recommendation: str
    timestamp: float


@dataclass(frozen=True)
class ComponentHealth:
    """Health of one component."""

    component: str
    status: HealthStatus
    score: int
    value: float | None
    findings: tuple[Finding, ...] = ()


@dataclass
class DeviceHealth:
    """The unified health of the connected device."""

    overall_score: float | None
    status: HealthStatus
    components: dict[str, ComponentHealth]
    findings: list[Finding] = field(default_factory=list)
    evaluated_at: float | None = None
    device_serial: str | None = None

    def component(self, key: str) -> ComponentHealth | None:
        """Health of one component key (or None when not evaluated)."""
        return self.components.get(key)


__all__ = [
    "COMPONENT_APPLICATIONS",
    "COMPONENT_BATTERY",
    "COMPONENT_CONNECTIVITY",
    "COMPONENT_CPU",
    "COMPONENT_MEMORY",
    "COMPONENT_PROCESSES",
    "COMPONENT_STORAGE",
    "ComponentHealth",
    "DeviceHealth",
    "Finding",
    "HealthSeverity",
    "HealthStatus",
]
