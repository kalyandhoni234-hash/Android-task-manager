"""Action capability and target validation for device management.

The action service executes what it is told; this module decides what the
*device context* allows. It is the capability gate between the GUI and the
service: a system application must never receive an uninstall or disable
button just because the ADB command exists.

Capability rules are deliberately conservative and platform-agnostic:

* user apps may be launched, inspected, force-stopped, enabled/disabled
  and uninstalled;
* system apps may be launched, inspected and force-stopped, but never
  uninstalled or disabled through this tool — Android may allow it on some
  builds, but "can run the command" is not "is safe to offer".

The module is pure (no ADB, no Qt): it takes the plain booleans a caller
has already classified and returns action names or raises a typed
:class:`ActionError`.
"""

from __future__ import annotations

from .models import ActionError, ActionErrorKind

#: Canonical management action names understood by the GUI action layer.
LAUNCH = "open_app"
APP_INFO = "app_info"
FORCE_STOP = "force_stop"
ENABLE = "enable"
DISABLE = "disable"
UNINSTALL = "uninstall"

#: Destructive operations: these always require an explicit confirmation
#: at the GUI layer before they are dispatched.
DESTRUCTIVE_ACTIONS = (FORCE_STOP, DISABLE, UNINSTALL)


def supported_actions(is_system: bool, enabled: bool | None) -> tuple[str, ...]:
    """Return the actions the device context permits for one application.

    ``enabled`` may be unknown (``None``); enable/disable are then both
    omitted instead of guessed.
    """
    actions = [LAUNCH, APP_INFO, FORCE_STOP]
    if not is_system:
        if enabled is False:
            actions.append(ENABLE)
        elif enabled is True:
            actions.append(DISABLE)
        actions.append(UNINSTALL)
    return tuple(actions)


def validate_action(action: str, is_system: bool, enabled: bool | None) -> None:
    """Raise a typed :class:`ActionError` when *action* is not permitted.

    ``INVALID_TARGET`` is raised for unknown action names and
    ``NOT_SUPPORTED`` when the device context forbids a known action.
    """
    if action not in (LAUNCH, APP_INFO, FORCE_STOP, ENABLE, DISABLE, UNINSTALL):
        raise ActionError(
            ActionErrorKind.INVALID_TARGET,
            f"unknown action: {action!r}",
        )
    if action in supported_actions(is_system, enabled):
        return
    if is_system:
        if action in (UNINSTALL, DISABLE):
            raise ActionError(
                ActionErrorKind.NOT_SUPPORTED,
                "This action is not supported for system applications.",
            )
    if action in (ENABLE, DISABLE):
        raise ActionError(
            ActionErrorKind.NOT_SUPPORTED,
            "This action is not supported for this application state.",
        )
    raise ActionError(
        ActionErrorKind.NOT_SUPPORTED,
        f"Action {action!r} is not supported for this application.",
    )


__all__ = [
    "APP_INFO",
    "DESTRUCTIVE_ACTIONS",
    "DISABLE",
    "ENABLE",
    "FORCE_STOP",
    "LAUNCH",
    "UNINSTALL",
    "supported_actions",
    "validate_action",
]