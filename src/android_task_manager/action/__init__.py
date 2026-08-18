"""Controlled device actions: open app, app info, force stop, enable/disable, uninstall.

The action layer holds the only allowed application-level AM/PM command
shapes in the project. Everything executes through the shared
``CommandRunner`` abstraction with validated package names, and every
action is gated by the capability rules in :mod:`capability`.
"""

from __future__ import annotations

from .capability import (
    APP_INFO,
    DESTRUCTIVE_ACTIONS,
    DISABLE,
    ENABLE,
    FORCE_STOP,
    LAUNCH,
    UNINSTALL,
    supported_actions,
    validate_action,
)
from .models import ActionError, ActionErrorKind, ActionResult
from .package import (
    COMPONENT_RE,
    MAX_PACKAGE_LENGTH,
    PACKAGE_NAME_RE,
    PackageValidationError,
    parse_package_list,
    validate_component,
    validate_package_name,
)
from .resolution import (
    is_kernel_style_name,
    parse_command_line_argv0,
    resolve_package,
    strip_secondary_suffix,
)
from .resolver import PackageResolver
from .service import ActionService

__all__ = [
    "APP_INFO",
    "ActionError",
    "ActionErrorKind",
    "ActionResult",
    "ActionService",
    "COMPONENT_RE",
    "DESTRUCTIVE_ACTIONS",
    "DISABLE",
    "ENABLE",
    "FORCE_STOP",
    "LAUNCH",
    "MAX_PACKAGE_LENGTH",
    "PACKAGE_NAME_RE",
    "PackageResolver",
    "PackageValidationError",
    "UNINSTALL",
    "is_kernel_style_name",
    "parse_command_line_argv0",
    "parse_package_list",
    "resolve_package",
    "strip_secondary_suffix",
    "supported_actions",
    "validate_action",
    "validate_component",
    "validate_package_name",
]