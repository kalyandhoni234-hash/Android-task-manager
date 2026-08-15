"""Controlled device actions: open app, app info, force stop.

The action layer holds the only allowed application-level AM/PM command
shapes in the project. Everything executes through the shared
``CommandRunner`` abstraction with validated package names.
"""

from __future__ import annotations

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
    "ActionError",
    "ActionErrorKind",
    "ActionResult",
    "ActionService",
    "COMPONENT_RE",
    "MAX_PACKAGE_LENGTH",
    "PACKAGE_NAME_RE",
    "PackageResolver",
    "PackageValidationError",
    "is_kernel_style_name",
    "parse_command_line_argv0",
    "parse_package_list",
    "resolve_package",
    "strip_secondary_suffix",
    "validate_component",
    "validate_package_name",
]