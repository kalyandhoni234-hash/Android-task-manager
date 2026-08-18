"""Device health engine: unified, deterministic device health model.

Pure and testable without a GUI or a device: consumes the normalized live
snapshots, classifies components with the canonical thresholds, and
produces a deterministic overall score, status and findings.
"""

from .engine import evaluate_device_health
from .models import (
    COMPONENT_APPLICATIONS,
    COMPONENT_BATTERY,
    COMPONENT_CONNECTIVITY,
    COMPONENT_CPU,
    COMPONENT_MEMORY,
    COMPONENT_PROCESSES,
    COMPONENT_STORAGE,
    ComponentHealth,
    DeviceHealth,
    Finding,
    HealthSeverity,
    HealthStatus,
)

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
    "evaluate_device_health",
]
