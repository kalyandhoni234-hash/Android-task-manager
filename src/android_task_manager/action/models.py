"""Typed results and errors for controlled device actions.

The action layer never returns raw strings from deep under the GUI: every
completed action is a frozen :class:`ActionResult` that carries a typed
:class:`ActionErrorKind`, so the GUI can render a clean user-facing message
without parsing text or exposing tracebacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


#: Human-meaningful, machine-checkable failure categories. These map 1:1 to
#: the existing typed ADB exception hierarchy plus validation failures.
class ActionErrorKind(Enum):
    INVALID_PACKAGE = "invalid_package"
    NOT_FOUND = "not_found"
    NOT_LAUNCHABLE = "not_launchable"
    DISCONNECTED = "disconnected"
    UNAUTHORIZED = "unauthorized"
    NO_DEVICE = "no_device"
    ADB_MISSING = "adb_missing"
    TIMEOUT = "timeout"
    COMMAND_FAILED = "command_failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ActionResult:
    """Typed outcome of one device action."""

    action: str
    package_name: str
    success: bool
    message: str = ""
    error_kind: ActionErrorKind | None = None


class ActionError(Exception):
    """Error raised by :class:`~android_task_manager.action.service.ActionService`.

    Carries a typed :class:`ActionErrorKind` plus a message that is safe to
    show to the user (no tracebacks, no raw stderr).
    """

    def __init__(self, kind: ActionErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message