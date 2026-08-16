"""ConnectionManager reconfiguration tests (setters + device details).

``subprocess.run`` is stubbed, so no adb binary or device is needed.
"""

from __future__ import annotations

from types import SimpleNamespace

from android_task_manager.adb.connection import ConnectionManager


class _FakeRun:
    """Records invocations and returns canned output."""

    def __init__(self, stdout: str = "", exit_code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.call_kwargs: list[dict] = []
        self.stdout = stdout
        self.exit_code = exit_code
        self.raise_timeout = False

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        self.call_kwargs.append(dict(kwargs))
        if self.raise_timeout:
            raise __import__("subprocess").TimeoutExpired(args[0], kwargs.get("timeout", 10))
        return SimpleNamespace(stdout=self.stdout, stderr="", returncode=self.exit_code)


def test_set_adb_path_switches_executable(monkeypatch) -> None:
    fake = _FakeRun()
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = ConnectionManager(adb_path="old-adb")
    connection.execute(["version"])
    connection.set_adb_path("C:\\new location\\adb.exe")
    connection.execute(["version"])
    assert fake.calls[0][0] == "old-adb"
    assert fake.calls[1][0] == "C:\\new location\\adb.exe"


def test_set_device_serial_pins_require_device(monkeypatch) -> None:
    fake = _FakeRun(stdout="List of devices attached\nA1\tdevice\nB2\tdevice\n")
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = ConnectionManager(adb_path="adb")
    connection.set_device_serial("B2")
    assert connection.require_device() == "B2"
    # Unpinning with several devices present is ambiguous again.
    import pytest

    from android_task_manager.adb.exceptions import ADBAmbiguousDeviceError

    connection.set_device_serial(None)
    with pytest.raises(ADBAmbiguousDeviceError):
        connection.require_device()


def test_get_device_details_reads_properties_per_serial(monkeypatch) -> None:
    values = {
        "ro.product.manufacturer": "vivo",
        "ro.product.model": "V2026",
        "ro.build.version.release": "11",
    }

    class _PropFakeRun(_FakeRun):
        def __call__(self, args, **kwargs):
            super().__call__(args, **kwargs)
            return SimpleNamespace(
                stdout=values.get(args[-1], ""), stderr="", returncode=0
            )

    fake = _PropFakeRun()
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = ConnectionManager(adb_path="adb", timeout=30.0)
    details = connection.get_device_details("A1")
    assert details["ro.product.manufacturer"] == "vivo"
    assert details["ro.product.model"] == "V2026"
    assert details["ro.build.version.release"] == "11"
    assert len(fake.calls) == 3
    for call in fake.calls:
        assert call[1] == "-s"
        assert call[2] == "A1"


def test_get_device_details_tolerates_failures(monkeypatch) -> None:
    fake = _FakeRun(exit_code=1)
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = ConnectionManager(adb_path="adb")
    details = connection.get_device_details("A1")
    assert details == {
        "ro.product.manufacturer": "",
        "ro.product.model": "",
        "ro.build.version.release": "",
    }


def test_get_device_details_tolerates_timeouts(monkeypatch) -> None:
    fake = _FakeRun()
    fake.raise_timeout = True
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = ConnectionManager(adb_path="adb")
    details = connection.get_device_details("A1")
    assert all(value == "" for value in details.values())
    # The per-property timeout must be short and bounded.
    assert fake.call_kwargs
    assert all(kwargs["timeout"] <= 5.0 for kwargs in fake.call_kwargs)


def test_execute_hides_console_for_windows_child_processes(monkeypatch) -> None:
    import subprocess
    import sys

    fake = _FakeRun()
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = ConnectionManager(adb_path="adb")
    connection.execute(["devices"])

    # adb.exe is a console-subsystem binary; spawned from a GUI-subsystem
    # parent it would flash a console window on every call unless suppressed.
    # The creation flag must be CREATE_NO_WINDOW on Windows and 0 elsewhere.
    assert fake.call_kwargs
    expected = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    assert fake.call_kwargs[0]["creationflags"] == expected

    # stdout/stderr must stay captured (pipes) regardless of the flag.
    assert fake.call_kwargs[0]["capture_output"] is True


class _DecodingFakeRun:
    """Mimics subprocess's text-mode decode with the requested codec.

    Real ``subprocess.run(..., text=True, encoding=..., errors=...)`` decodes
    the captured bytes with those exact parameters; the fake applies the
    same contract so the tests prove what the call site passes and that
    malformed device bytes cannot escape as UnicodeDecodeError.
    """

    def __init__(self, stdout: bytes, stderr: bytes = b"") -> None:
        self.kwargs: dict | None = None
        self.stdout_bytes = stdout
        self.stderr_bytes = stderr

    def __call__(self, args, **kwargs):
        self.kwargs = dict(kwargs)
        return SimpleNamespace(
            stdout=self.stdout_bytes.decode(
                kwargs.get("encoding", "utf-8"), kwargs.get("errors", "replace")
            ),
            stderr=self.stderr_bytes.decode(
                kwargs.get("encoding", "utf-8"), kwargs.get("errors", "replace")
            ),
            returncode=0,
        )


def test_execute_decodes_utf8_output(monkeypatch) -> None:
    """Non-ASCII UTF-8 device output must decode intact (no locale mojibake)."""
    fake = _DecodingFakeRun("V2026 \u00fcber-ASCII \u65e5\u672c\u8a9e".encode("utf-8"))
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = ConnectionManager(adb_path="adb")

    result = connection.execute(["getprop", "ro.product.model"])

    assert result.stdout == "V2026 \u00fcber-ASCII \u65e5\u672c\u8a9e"


def test_execute_tolerates_malformed_device_bytes(monkeypatch) -> None:
    """Malformed bytes must decode with U+FFFD, never raise UnicodeDecodeError."""
    fake = _DecodingFakeRun(b"model: \xff\xfe\x00garbage")
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = ConnectionManager(adb_path="adb")

    result = connection.execute(["getprop", "ro.product.model"])

    assert "\ufffd" in result.stdout
    assert result.exit_code == 0


def test_execute_requests_utf8_with_replace_policy(monkeypatch) -> None:
    """The call site must explicitly request UTF-8 + the replace error policy."""
    fake = _DecodingFakeRun(b"")
    monkeypatch.setattr("android_task_manager.adb.connection.subprocess.run", fake)
    connection = ConnectionManager(adb_path="adb")
    connection.execute(["version"])

    assert fake.kwargs is not None
    assert fake.kwargs["encoding"] == "utf-8"
    assert fake.kwargs["errors"] == "replace"