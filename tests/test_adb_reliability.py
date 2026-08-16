"""ADB reliability tests: device-loss detection, typed error mapping.

``subprocess.run`` is stubbed, so no adb binary or device is needed. Covers
the failure modes Phase 1 must handle cleanly: missing adb, no device,
unauthorized, offline, multiple devices, timeout, command failure, raw
subprocess failures and disconnect/reconnect behavior.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from android_task_manager.adb.connection import ConnectionManager
from android_task_manager.adb.exceptions import (
    ADBAmbiguousDeviceError,
    ADBCommandError,
    ADBDisconnectedError,
    ADBError,
    ADBNoDeviceError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)

_DEVICES_OK = "List of devices attached\nA1\tdevice\n"
_DEVICES_NONE = "List of devices attached\n"
_DEVICES_OFFLINE = "List of devices attached\nA1\toffline\n"
_DEVICES_UNAUTHORIZED = "List of devices attached\nA1\tunauthorized\n"
_DEVICES_MULTIPLE = "List of devices attached\nA1\tdevice\nB2\tdevice\n"


class _ScriptedRun:
    """Canned ``subprocess.run``: one step per call, then defaults."""

    def __init__(self, script: list[tuple[str, str, int]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.script = list(script or [])

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if self.script:
            stdout, stderr, code = self.script.pop(0)
        else:
            stdout, stderr, code = "", "", 0
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=code)


class _RaisingRun:
    """``subprocess.run`` that raises a raw error (must be mapped)."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        raise self.error


def _connection(fake) -> ConnectionManager:
    return ConnectionManager(adb_path="adb")


# ---------------------------------------------------------------------------
# Raw subprocess failure mapping (execute)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [PermissionError("access denied"), OSError("broken pipe during communicate")],
)
def test_execute_maps_raw_subprocess_errors_to_adb_error(monkeypatch, error) -> None:
    fake = _RaisingRun(error)
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = _connection(fake)
    with pytest.raises(ADBError):
        connection.execute(["version"])


def test_execute_maps_missing_adb_to_adb_not_found(monkeypatch) -> None:
    fake = _RaisingRun(FileNotFoundError("adb"))
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = _connection(fake)
    with pytest.raises(ADBError):
        connection.execute(["version"])


def test_execute_maps_timeout_to_adb_timeout(monkeypatch) -> None:
    import subprocess

    fake = _RaisingRun(subprocess.TimeoutExpired("adb", 10.0))
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = _connection(fake)
    with pytest.raises(ADBTimeoutError):
        connection.execute(["shell", "sleep"])


# ---------------------------------------------------------------------------
# Device table states (require_device)
# ---------------------------------------------------------------------------


def test_require_device_no_device(monkeypatch) -> None:
    fake = _ScriptedRun([(_DEVICES_NONE, "", 0)])
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    with pytest.raises(ADBNoDeviceError):
        _connection(fake).require_device()


def test_require_device_multiple_devices_is_ambiguous(monkeypatch) -> None:
    fake = _ScriptedRun([(_DEVICES_MULTIPLE, "", 0)])
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    with pytest.raises(ADBAmbiguousDeviceError) as info:
        _connection(fake).require_device()
    assert info.value.serials == ["A1", "B2"]


def test_require_device_offline_is_disconnected(monkeypatch) -> None:
    fake = _ScriptedRun([(_DEVICES_OFFLINE, "", 0)])
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    with pytest.raises(ADBDisconnectedError):
        _connection(fake).require_device()


def test_require_device_unauthorized(monkeypatch) -> None:
    fake = _ScriptedRun([(_DEVICES_UNAUTHORIZED, "", 0)])
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    with pytest.raises(ADBUnauthorizedError):
        _connection(fake).require_device()


def test_require_device_pinned_serial_gone_is_disconnected(monkeypatch) -> None:
    fake = _ScriptedRun([(_DEVICES_NONE, "", 0)])
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = _connection(fake)
    connection.set_device_serial("A1")
    with pytest.raises(ADBDisconnectedError):
        connection.require_device()


# ---------------------------------------------------------------------------
# Command failure mapping (shell) — device vanishing mid-command
# ---------------------------------------------------------------------------


def test_shell_offline_during_command_is_disconnected(monkeypatch) -> None:
    fake = _ScriptedRun(
        [
            (_DEVICES_OK, "", 0),
            ("", "error: device offline", 1),
        ]
    )
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    with pytest.raises(ADBDisconnectedError):
        _connection(fake).shell(["getprop", "ro.product.model"])


def test_shell_device_not_found_is_disconnected(monkeypatch) -> None:
    fake = _ScriptedRun(
        [
            (_DEVICES_OK, "", 0),
            ("", "error: device 'A1' not found", 1),
        ]
    )
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    with pytest.raises(ADBDisconnectedError):
        _connection(fake).shell(["getprop", "ro.product.model"])


def test_shell_no_devices_mid_command_is_disconnected(monkeypatch) -> None:
    fake = _ScriptedRun(
        [
            (_DEVICES_OK, "", 0),
            ("", "error: no devices/emulators found", 1),
        ]
    )
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    with pytest.raises(ADBDisconnectedError):
        _connection(fake).shell(["getprop", "ro.product.model"])


def test_shell_closed_device_is_disconnected(monkeypatch) -> None:
    fake = _ScriptedRun(
        [
            (_DEVICES_OK, "", 0),
            ("", "error: closed", 1),
        ]
    )
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    with pytest.raises(ADBDisconnectedError):
        _connection(fake).shell(["getprop", "ro.product.model"])


def test_shell_unauthorized_during_command(monkeypatch) -> None:
    fake = _ScriptedRun(
        [
            (_DEVICES_OK, "", 0),
            ("", "error: device unauthorized.", 1),
        ]
    )
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    with pytest.raises(ADBUnauthorizedError):
        _connection(fake).shell(["getprop", "ro.product.model"])


def test_shell_command_failure_raises_command_error(monkeypatch) -> None:
    fake = _ScriptedRun(
        [
            (_DEVICES_OK, "", 0),
            ("", "getprop: not found", 127),
        ]
    )
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    with pytest.raises(ADBCommandError) as info:
        _connection(fake).shell(["getprop", "ro.product.model"])
    assert info.value.exit_code == 127


# ---------------------------------------------------------------------------
# Disconnect → reconnect behavior
# ---------------------------------------------------------------------------


def test_disconnect_then_reconnect_recovers(monkeypatch) -> None:
    """A device that drops mid-session and returns can be used again."""
    fake = _ScriptedRun(
        [
            (_DEVICES_OK, "", 0),
            ("", "error: device 'A1' not found", 1),  # device vanishes
            (_DEVICES_OK, "", 0),
            ("vivo", "", 0),  # device is back
        ]
    )
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = _connection(fake)
    with pytest.raises(ADBDisconnectedError):
        connection.shell(["getprop", "ro.product.manufacturer"])
    # No recovery needed on the connection side: the next command just works.
    assert connection.shell(["getprop", "ro.product.manufacturer"]) == "vivo"


def test_get_device_details_never_raises_on_device_loss(monkeypatch) -> None:
    """The multi-device picker stays alive even when devices vanish mid-read."""
    fake = _ScriptedRun(
        [
            ("", "error: device 'A1' not found", 1),
            ("", "error: no devices/emulators found", 1),
            ("", "error: device offline", 1),
        ]
    )
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    details = _connection(fake).get_device_details("A1")
    assert details == {
        "ro.product.manufacturer": "",
        "ro.product.model": "",
        "ro.build.version.release": "",
    }