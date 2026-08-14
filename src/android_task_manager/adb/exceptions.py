"""ADB-specific exception hierarchy."""

from __future__ import annotations

from typing import Sequence


class ADBError(Exception):
    """Base class for all ADB-related failures."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.__class__.__doc__ or "")


class ADBNotFoundError(ADBError):
    """The adb executable could not be found / started."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "adb executable was not found or could not be run.")


class ADBNoDeviceError(ADBError):
    """No Android device is currently connected."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "No authorized Android device is connected to adb.")


class ADBUnauthorizedError(ADBError):
    """A device is present but the host is not authorized to use it."""

    def __init__(self, serial: str | None = None) -> None:
        self.serial = serial
        if serial:
            super().__init__(f"Device {serial} is unauthorized. Authorize this computer on the device.")
        else:
            super().__init__("A device is connected but unauthorized. Authorize it on the phone.")


class ADBDisconnectedError(ADBError):
    """A device that should be present is offline / gone."""

    def __init__(self, detail: str | None = None) -> None:
        if detail:
            super().__init__(detail)
        else:
            super().__init__("No authorized device is connected to adb.")


class ADBAmbiguousDeviceError(ADBError):
    """More than one authorized device is connected and none was specified."""

    def __init__(self, serials: Sequence[str]) -> None:
        self.serials = list(serials)
        shown = ", ".join(self.serials) if self.serials else "unknown"
        super().__init__(
            f"More than one authorized device is connected ({shown}). "
            "Disconnect the extras or pass an explicit --device serial."
        )


class ADBTimeoutError(ADBError):
    """An adb command exceeded its allowed time budget."""

    def __init__(self, command: str, timeout: float) -> None:
        self.command = command
        self.timeout = timeout
        super().__init__(f"adb command timed out after {timeout:.1f}s: {command}")


class ADBCommandError(ADBError):
    """An adb command returned a non-zero exit status."""

    def __init__(
        self,
        command: str,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        message = f"adb command failed with exit code {exit_code}: {command}"
        extra = stderr.strip()
        if extra:
            message += f"\n{extra}"
        super().__init__(message)