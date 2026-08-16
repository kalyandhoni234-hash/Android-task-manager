"""Central ADB execution layer.

This module is the **only** place in the codebase allowed to call ``subprocess``.
It is responsible for locating adb, discovering the attached device, executing
remote ``adb shell`` commands, enforcing timeouts and raising meaningful,
typed exceptions on failure.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Protocol, Sequence

from ..core.diagnostics import register_secret
from .exceptions import (
    ADBAmbiguousDeviceError,
    ADBCommandError,
    ADBDisconnectedError,
    ADBError,
    ADBNoDeviceError,
    ADBNotFoundError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)

logger = logging.getLogger("android_task_manager.adb.connection")

#: Token set by adb for an online, authorized device in ``adb devices`` output.
_AUTHORIZED_STATE = "device"
#: Regular expression field indexes from ``adb devices`` output lines.
_DEVICE_LIST_HEADER_START = "List of devices"


@dataclass(frozen=True)
class ADBCommandResult:
    """Captured outcome of a single adb invocation."""

    stdout: str
    stderr: str
    exit_code: int


@dataclass(frozen=True)
class Device:
    """An entry from ``adb devices``."""

    serial: str
    state: str


class CommandRunner(Protocol):
    """Minimal ADB facade used by collectors and workers (ConnectionManager).

    Keeping this as an interface lets collectors be tested with fakes rather
    than a real device or ``subprocess``. The connection lifecycle methods
    are part of the contract because the monitor worker drives connect /
    retry / multi-device selection through this same interface.
    """

    def shell(self, args: Sequence[str], timeout: float | None = None) -> str: ...

    def verify_available(self) -> None: ...

    def require_device(self) -> str: ...

    def list_devices(self) -> list[Device]: ...

    def get_device_details(self, serial: str) -> dict[str, str]: ...


class ConnectionManager:
    """Finds an attached Android device and runs remote shell commands on it."""

    def __init__(
        self,
        adb_path: str = "adb",
        timeout: float = 10.0,
        device_serial: str | None = None,
    ) -> None:
        self._adb_path = adb_path
        self._timeout = timeout
        self._device_serial = device_serial

    def set_adb_path(self, adb_path: str) -> None:
        """Point this connection at a different adb executable.

        All collectors and workers that share this ConnectionManager (the
        design used by the GUI) pick up the new path on their next command.
        """
        self._adb_path = adb_path

    def set_device_serial(self, device_serial: str | None) -> None:
        """Pin (or unpin) the target device by serial."""
        self._device_serial = device_serial

    # ------------------------------------------------------------------
    # Availability / discovery
    # ------------------------------------------------------------------

    def verify_available(self) -> None:
        """Assert adb is installed and runnable; raise otherwise."""
        try:
            result = self.execute(["version"])
        except ADBNotFoundError:
            raise
        except ADBError:
            raise
        if result.exit_code != 0:
            raise ADBError(
                f"`adb version` failed with exit code {result.exit_code}: "
                f"{result.stderr.strip()}"
            )

    def list_devices(self) -> list[Device]:
        """Return the current device table from ``adb devices``."""
        result = self.execute(["devices"])
        devices: list[Device] = []
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line or line.startswith(_DEVICE_LIST_HEADER_START):
                continue
            parts = line.split()
            if len(parts) < 2 or parts[0] == "*":
                # Ignore decorations such as "daemon started successfully".
                continue
            serial, state = parts[0], parts[1]
            # Serials are secrets: registering them keeps every formatted
            # log line scrubbed (errors from adb quote serials too).
            register_secret(serial)
            devices.append(Device(serial=serial, state=state))
        return devices

    def require_device(self) -> str:
        """Select the target device serial or raise a descriptive ADBError."""
        devices = self.list_devices()

        if self._device_serial is not None:
            for device in devices:
                if device.serial == self._device_serial:
                    if device.state == _AUTHORIZED_STATE:
                        return device.serial
                    self._raise_for_state(device)
            raise ADBDisconnectedError(
                f"Specified device {self._device_serial} is not present."
            )

        authorized = [d for d in devices if d.state == _AUTHORIZED_STATE]
        if len(authorized) == 1:
            return authorized[0].serial
        if len(authorized) > 1:
            raise ADBAmbiguousDeviceError([d.serial for d in authorized])

        for device in devices:
            self._raise_for_state(device)
        raise ADBNoDeviceError()

    @staticmethod
    def _raise_for_state(device: Device) -> None:
        if device.state == "unauthorized":
            raise ADBUnauthorizedError(device.serial)
        if device.state == "offline":
            raise ADBDisconnectedError(
                f"Device {device.serial} is present but offline."
            )
        # Any other non-negotiated state is treated as not usable.
        raise ADBDisconnectedError(
            f"Device {device.serial} is not ready (state: {device.state})."
        )

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def execute(
        self,
        args: Sequence[str],
        timeout: float | None = None,
    ) -> ADBCommandResult:
        """Run an adb subcommand with safe argument lists and timeouts."""
        full_args = [self._adb_path, *args]
        try:
            completed = subprocess.run(
                full_args,
                capture_output=True,
                text=True,
                # Android device output is UTF-8. An explicit codec keeps the
                # decode independent of the host locale (Windows ANSI
                # codepages would otherwise mangle or crash on non-ASCII
                # output); "replace" turns malformed device bytes into U+FFFD
                # instead of raising UnicodeDecodeError.
                encoding="utf-8",
                errors="replace",
                timeout=timeout if timeout is not None else self._timeout,
                check=False,
                # On Windows every adb call would otherwise flash a console
                # window (adb.exe is a console-subsystem binary and the
                # packaged GUI parent is a GUI-subsystem process). The flag is
                # ignored on POSIX, where adb has no console concept. It is
                # resolved via getattr so non-Windows type stubs (mypy in CI)
                # accept the reference; the runtime value is 0 off Windows.
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform == "win32"
                    else 0
                ),
            )
        except FileNotFoundError as exc:
            raise ADBNotFoundError(
                f"adb executable not found at '{self._adb_path}'. "
                "Install Android platform-tools or pass --adb."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            command = " ".join(args)
            raise ADBTimeoutError(
                command,
                timeout if timeout is not None else self._timeout,
            ) from exc
        except OSError as exc:
            # Anything else that prevents adb from launching (permissions,
            # a vanished executable, broken pipes when a device drops mid-
            # command on Windows) maps to the typed hierarchy, never a raw
            # subprocess error escaping to collectors/workers/GUI.
            raise ADBError(f"adb could not be started: {exc}") from exc
        return ADBCommandResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )

    def shell(
        self,
        args: Sequence[str],
        timeout: float | None = None,
    ) -> str:
        """Run ``adb shell <args>`` on the target device and return stdout text.

        Raises typed exceptions on missing adb, no/unauthorized/offline device,
        timeouts, and non-zero remote exit status.
        """
        serial = self.require_device()
        result = self.execute(["-s", serial, "shell", *args], timeout=timeout)
        if result.exit_code != 0:
            stderr = result.stderr
            if self._device_lost(stderr):
                raise ADBDisconnectedError(
                    f"Device {serial} is no longer available "
                    f"(offline, gone, or adb server lost it): {stderr.strip()}"
                )
            if "unauthorized" in stderr:
                raise ADBUnauthorizedError(serial)
            raise ADBCommandError(
                "shell " + " ".join(args),
                result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result.stdout

    @staticmethod
    def _device_lost(stderr: str) -> bool:
        """True when adb's error text means the target device is gone.

        Matches the states a device can fall into mid-command: ``offline``,
        ``closed``, a vanished serial (``device '...' not found``) and a
        vanished server/device table (``no devices/emulators found``). adb
        prints these to stderr with a non-zero exit status.
        """
        lowered = stderr.lower()
        if "offline" in lowered or "closed" in lowered:
            return True
        if "no devices/emulators found" in lowered:
            return True
        # "not found" alone is ambiguous: a remote command can fail with
        # "getprop: not found" while the device is perfectly healthy. Only
        # treat it as device loss when adb itself reports a vanished device
        # ("error: device 'A1' not found").
        if "not found" in lowered and ("device" in lowered or "emulator" in lowered):
            return True
        return False

    def get_prop(self, name: str) -> str:
        """Read a device system property (empty string if unset)."""
        return self.shell(["getprop", name]).strip()

    def get_device_details(self, serial: str) -> dict[str, str]:
        """Best-effort identity details for a specific device serial.

        Runs three cheap ``getprop`` reads (manufacturer, model, Android
        version) on the named serial, tolerating per-property failures so the
        multi-device selection UI never dies on a flaky device. Keys mirror the
        property names, with missing values reported as empty strings.
        """
        details: dict[str, str] = {}
        for prop in (
            "ro.product.manufacturer",
            "ro.product.model",
            "ro.build.version.release",
        ):
            try:
                result = self.execute(
                    ["-s", serial, "shell", "getprop", prop],
                    timeout=min(self._timeout, 5.0),
                )
                details[prop] = result.stdout.strip() if result.exit_code == 0 else ""
            except ADBError:
                details[prop] = ""
        return details