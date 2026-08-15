"""ActionService: the high-level layer for controlled device actions.

The service knows WHAT to do (open an app, show app info, force-stop a
package); :class:`~android_task_manager.adb.connection.ConnectionManager`
knows HOW to run ADB commands. The service never builds a shell command
from user input: every remote call is a fixed argument list plus a
strictly validated package name, executed through the shared
``CommandRunner.shell()`` with an explicit timeout.

Supported actions are limited to the three application-level operations:

* ``open_app``    - launch a package's main activity
* ``app_info``    - open Android's system App Info page
* ``force_stop``  - Android package-level force stop (never PID killing)
"""

from __future__ import annotations

from ..adb.exceptions import (
    ADBCommandError,
    ADBDisconnectedError,
    ADBError,
    ADBNotFoundError,
    ADBNoDeviceError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)
from .models import ActionError, ActionErrorKind, ActionResult
from .package import parse_package_list, validate_component, validate_package_name

LAUNCHER_CATEGORY = "android.intent.category.LAUNCHER"
MAIN_ACTION = "android.intent.action.MAIN"
APP_DETAILS_SETTINGS = "android.settings.APPLICATION_DETAILS_SETTINGS"

_KNOWN_ACTIONS = ("open_app", "app_info", "force_stop")


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
        )
    )


class ActionService:
    """Runs the three controlled device actions over a CommandRunner."""

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
                ActionErrorKind.INVALID_PACKAGE,
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
        )

    def force_stop(self, package: str) -> ActionResult:
        """Force-stop *package* at the Android package level (not a PID kill)."""
        self._shell(["am", "force-stop", package], package)
        return ActionResult(
            action="force_stop",
            package_name=package,
            success=True,
            message=f"Force stopped {package}",
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
            return ActionError(
                ActionErrorKind.COMMAND_FAILED,
                "The action failed on the device.",
            )
        return ActionError(
            ActionErrorKind.COMMAND_FAILED,
            "The action failed on the device.",
        )