"""ActionService: the high-level layer for controlled device actions.

The service knows WHAT to do (open an app, show app info, force-stop,
enable/disable or uninstall a package); :class:`~android_task_manager.adb.connection.ConnectionManager`
knows HOW to run ADB commands. The service never builds a shell command
from user input: every remote call is a fixed argument list plus a
strictly validated package name, executed through the shared
``CommandRunner.shell()`` with an explicit timeout.

Supported actions are limited to the application-level operations:

* ``open_app``    - launch a package's main activity
* ``app_info``    - open Android's system App Info page
* ``force_stop``  - Android package-level force stop (never PID killing)
* ``enable``      - re-enable a user-disabled package
* ``disable``     - disable a user package (``pm disable-user``, no root)
* ``uninstall``   - uninstall a user package

Destructive actions (force stop, disable, uninstall) are always gated by
the caller through :mod:`~android_task_manager.action.capability`; the
service itself only ever executes validated package commands.
"""

from __future__ import annotations

from ..adb.exceptions import (
    ADBCommandError,
    ADBDisconnectedError,
    ADBError,
    ADBNoDeviceError,
    ADBNotFoundError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)
from .models import ActionError, ActionErrorKind, ActionResult
from .package import parse_package_list, validate_component, validate_package_name

LAUNCHER_CATEGORY = "android.intent.category.LAUNCHER"
MAIN_ACTION = "android.intent.action.MAIN"
APP_DETAILS_SETTINGS = "android.settings.APPLICATION_DETAILS_SETTINGS"

_KNOWN_ACTIONS = ("open_app", "app_info", "force_stop", "enable", "disable", "uninstall")

#: Denial markers Android emits when a command is refused (``SecurityException``
#: text, "Operation not allowed", "Permission Denial"). Detection runs on the
#: command output even when the shell exit code is zero.
_PERMISSION_DENIED_MARKERS = (
    "operation not allowed",
    "security exception",
    "securityexception",
    "permission denial",
    "permissiondenial",
    "not permitted",
)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _is_not_found_hint(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "unknown package",
            "not found",
            "does not exist",
            "no activities found",
            "not installed",
        )
    )


def _is_permission_denied(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    return any(marker in lowered for marker in _PERMISSION_DENIED_MARKERS)


class ActionService:
    """Runs the controlled device actions over a CommandRunner."""

    def __init__(self, runner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, action: str, package: object) -> ActionResult:
        """Dispatch *action* for *package*, returning a typed result.

        Every failure is reported as a typed :class:`ActionResult` through
        :class:`ActionError`; nothing leaks raw device output.
        """
        if action not in _KNOWN_ACTIONS:
            raise ActionError(
                ActionErrorKind.INVALID_TARGET,
                f"unknown action: {action!r}",
            )
        try:
            validated = validate_package_name(package)
        except ValueError as exc:
            raise ActionError(ActionErrorKind.INVALID_PACKAGE, str(exc)) from exc
        if action == "open_app":
            return self.open_app(validated)
        if action == "app_info":
            return self.open_app_info(validated)
        if action == "enable":
            return self.enable(validated)
        if action == "disable":
            return self.disable(validated)
        if action == "uninstall":
            return self.uninstall(validated)
        return self.force_stop(validated)

    def open_app(self, package: str) -> ActionResult:
        """Launch *package*'s launcher activity."""
        component = self._resolve_launcher(package)
        try:
            output = self._shell(
                ["am", "start", "-W", "-n", component],
                package,
            )
        except ActionError:
            raise
        if _is_not_found_hint(output) or "Error type 3" in output:
            raise ActionError(
                ActionErrorKind.COMMAND_FAILED,
                f"App {package} could not be launched on the device.",
            )
        return ActionResult(
            action="open_app",
            package_name=package,
            success=True,
            message=f"Opened {package}",
            target=package,
        )

    def open_app_info(self, package: str) -> ActionResult:
        """Open Android's system App Info page for *package*."""
        try:
            output = self._shell(
                [
                    "am",
                    "start",
                    "-a",
                    APP_DETAILS_SETTINGS,
                    "-d",
                    f"package:{package}",
                ],
                package,
            )
        except ActionError:
            raise
        if "Error type 3" in output:
            raise ActionError(
                ActionErrorKind.COMMAND_FAILED,
                f"App Info could not be opened for {package}.",
            )
        return ActionResult(
            action="app_info",
            package_name=package,
            success=True,
            message=f"Opened App Info for {package}",
            target=package,
        )

    def force_stop(self, package: str) -> ActionResult:
        """Force-stop *package* at the Android package level (not a PID kill)."""
        self._shell(["am", "force-stop", package], package)
        return ActionResult(
            action="force_stop",
            package_name=package,
            success=True,
            message=f"Force stopped {package}",
            target=package,
        )

    def enable(self, package: str) -> ActionResult:
        """Re-enable a package that was disabled for the primary user.

        Fails honestly with a typed result on devices that refuse the
        operation (permission denied, not found, protected package).
        """
        output = self._shell(["pm", "enable", package], package)
        if _is_permission_denied(output):
            raise ActionError(
                ActionErrorKind.PERMISSION_DENIED,
                f"{package} could not be enabled on this device.",
            )
        return ActionResult(
            action="enable",
            package_name=package,
            success=True,
            message=f"Enabled {package}",
            target=package,
        )

    def disable(self, package: str) -> ActionResult:
        """Disable *package* for the primary user (``pm disable-user``).

        Uses the non-root ``disable-user`` form: it is the only disable
        shape that works on ordinary user applications without privileged
        ADB, and Android itself rejects it for protected packages.
        """
        output = self._shell(
            ["pm", "disable-user", "--user", "0", package],
            package,
        )
        if _is_permission_denied(output):
            raise ActionError(
                ActionErrorKind.PERMISSION_DENIED,
                f"{package} could not be disabled on this device.",
            )
        return ActionResult(
            action="disable",
            package_name=package,
            success=True,
            message=f"Disabled {package}",
            target=package,
        )

    def uninstall(self, package: str) -> ActionResult:
        """Uninstall *package* for the primary user.

        The caller must have verified this is an uninstallable (user)
        application through the capability gate; the service executes the
        validated command and reports the typed outcome.
        """
        output = self._shell(["pm", "uninstall", package], package)
        if "failure" in output.lower() and "success" not in output.lower():
            raise ActionError(
                ActionErrorKind.COMMAND_FAILED,
                f"{package} could not be uninstalled on the device.",
            )
        return ActionResult(
            action="uninstall",
            package_name=package,
            success=True,
            message=f"Uninstalled {package}",
            target=package,
        )

    def list_packages(self) -> set[str]:
        """Read and validate the device's installed package list."""
        try:
            output = self._runner.shell(
                ["pm", "list", "packages"],
                timeout=self._timeout,
            )
        except ADBError as exc:
            raise self._translate(exc, "list_packages", "") from exc
        return parse_package_list(output)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_launcher(self, package: str) -> str:
        """Resolve the package's launcher activity to a validated component."""
        try:
            output = self._shell(
                [
                    "cmd",
                    "package",
                    "resolve-activity",
                    "--brief",
                    "-c",
                    LAUNCHER_CATEGORY,
                    "-a",
                    MAIN_ACTION,
                    package,
                ],
                package,
            )
        except ActionError:
            raise
        component = _first_line(output)
        if not component:
            raise ActionError(
                ActionErrorKind.NOT_LAUNCHABLE,
                f"{package} has no launchable activity.",
            )
        try:
            return validate_component(component)
        except ValueError as exc:
            raise ActionError(
                ActionErrorKind.NOT_LAUNCHABLE,
                f"{package} has no launchable activity.",
            ) from exc

    def _shell(self, args: list[str], package: str) -> str:
        """Run one ADB shell call with the service timeout; translate errors."""
        try:
            return self._runner.shell(args, timeout=self._timeout)
        except ADBError as exc:
            raise self._translate(exc, " ".join(args), package) from exc

    def _translate(self, exc: ADBError, command: str, package: str) -> ActionError:
        """Map typed ADB exceptions to typed, user-friendly action errors."""
        if isinstance(exc, ADBTimeoutError):
            return ActionError(
                ActionErrorKind.TIMEOUT,
                "The action timed out on the device. Try again.",
            )
        if isinstance(exc, ADBDisconnectedError):
            return ActionError(
                ActionErrorKind.DISCONNECTED,
                "Device disconnected. Reconnect your Android device and try again.",
            )
        if isinstance(exc, ADBUnauthorizedError):
            return ActionError(
                ActionErrorKind.UNAUTHORIZED,
                "Device is not authorized. Approve the USB debugging prompt "
                "on the phone and try again.",
            )
        if isinstance(exc, ADBNoDeviceError):
            return ActionError(
                ActionErrorKind.NO_DEVICE,
                "No authorized Android device is connected.",
            )
        if isinstance(exc, ADBNotFoundError):
            return ActionError(
                ActionErrorKind.ADB_MISSING,
                "adb executable was not found. Reinstall Android platform-tools "
                "or point the app at adb.exe.",
            )
        if isinstance(exc, ADBCommandError):
            if _is_not_found_hint(f"{exc.stderr} {exc.stdout}"):
                return ActionError(
                    ActionErrorKind.NOT_FOUND,
                    f"Package {package} was not found on the device. "
                    "Was it uninstalled?",
                )
            if _is_permission_denied(f"{exc.stderr} {exc.stdout}"):
                return ActionError(
                    ActionErrorKind.PERMISSION_DENIED,
                    f"The device refused this action for {package}.",
                )
            return ActionError(
                ActionErrorKind.COMMAND_FAILED,
                "The action failed on the device.",
            )
        return ActionError(
            ActionErrorKind.COMMAND_FAILED,
            "The action failed on the device.",
        )