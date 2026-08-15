"""Package/permission audit.

Reads one installed package's granted permissions (``dumpsys package``)
through ConnectionManager, normalizes them, and evaluates a small fixed set
of documented permission-combination flags ("worth reviewing" framing only
— never a verdict). Facts (parsing) and judgment (combination flags) live
in separate, independently testable modules.

Scope: one package per call. Bulk auditing, CLI/GUI surfaces and wiring
permission data into heuristics are separate follow-ups.
"""

from .collector import PermissionCollector
from .combinations import (
    FLAG_OVERLAY_ACCESSIBILITY,
    FLAG_SMS_ACCESSIBILITY_DEVICE_ADMIN,
    evaluate_combinations,
)
from .models import (
    PERMISSION_INSTALL,
    PERMISSION_RUNTIME,
    PERMISSION_UNKNOWN,
    CombinationFlag,
    PackagePermissionAudit,
    PermissionEntry,
)
from .parser import parse_dumpsys_package

__all__ = [
    "FLAG_OVERLAY_ACCESSIBILITY",
    "FLAG_SMS_ACCESSIBILITY_DEVICE_ADMIN",
    "PERMISSION_INSTALL",
    "PERMISSION_RUNTIME",
    "PERMISSION_UNKNOWN",
    "CombinationFlag",
    "PackagePermissionAudit",
    "PermissionCollector",
    "PermissionEntry",
    "evaluate_combinations",
    "parse_dumpsys_package",
]