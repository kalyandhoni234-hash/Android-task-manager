"""Serial-binding guard: one session, one device — no silent retargeting.

Priority #4 hardening. Deterministic, device-free:

* ``ConnectionManager`` level (real class, ``subprocess.run`` stubbed):
  a pinned/bound session resolves ONLY its own serial; a vanished or
  replaced serial is typed device loss; rebinding after loss starts a
  fresh identity; legacy unpinned single-device operation is preserved.
* ``MonitorWorker`` level (scripted fake connection, synchronous
  ``_connect``/``tick``): the discovered serial is pinned at connect, and
  device loss during sampling releases the binding so the next connect
  adopts whatever device is present as a NEW session.
"""

from __future__ import annotations

import pytest

from android_task_manager.adb.connection import ConnectionManager
from android_task_manager.adb.exceptions import ADBDisconnectedError

# --------------------------------------------------------------------------
# Fakes / helpers
# --------------------------------------------------------------------------

class _FakeRun:
    """Records ``adb ...`` invocations; only ``adb devices`` yields a table."""

    def __init__(self, stdout: str = "") -> None:
        self.calls: list[list[str]] = []
        self.stdout = stdout

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        from types import SimpleNamespace

        payload = self.stdout if "devices" in args else ""
        return SimpleNamespace(stdout=payload, stderr="", returncode=0)


def _patch_adb(monkeypatch, devices: tuple[tuple[str, str], ...]):
    rows = "".join(f"{serial}\t{state}\n" for serial, state in devices)
    fake = _FakeRun(stdout="List of devices attached\n" + rows)
    monkeypatch.setattr(
        "android_task_manager.adb.connection.subprocess.run", fake
    )
    return fake


def _shell_target_serials(fake: _FakeRun) -> list[str]:
    """The '-s <serial>' values of every remote shell invocation."""
    out = []
    for call in fake.calls:
        if "-s" in call:
            out.append(call[call.index("-s") + 1])
    return out


# --------------------------------------------------------------------------
# ConnectionManager: binding semantics
# --------------------------------------------------------------------------

def test_session_bound_serial_targets_only_that_device(monkeypatch) -> None:
    fake = _patch_adb(monkeypatch, [("A", "device"), ("B", "device")])
    cm = ConnectionManager()
    cm.set_device_serial("A")

    first = cm.shell(["getprop", "ro.product.model"])
    second = cm.shell(["getprop", "ro.build.version.release"])

    assert first == second == ""  # canned empty output, exit 0
    assert _shell_target_serials(fake) == ["A", "A"]


def test_command_cannot_silently_execute_against_another_device(monkeypatch) -> None:
    # Bound to A; A disappears and ONLY B remains authorized.
    fake = _patch_adb(monkeypatch, [("B", "device")])
    cm = ConnectionManager()
    cm.set_device_serial("A")

    with pytest.raises(ADBDisconnectedError):
        cm.shell(["getprop", "ro.product.model"])

    assert _shell_target_serials(fake) == []  # nothing executed against B


def test_vanished_bound_serial_is_device_loss(monkeypatch) -> None:
    _patch_adb(monkeypatch, [])  # no devices at all
    cm = ConnectionManager()
    cm.set_device_serial("A")

    with pytest.raises(ADBDisconnectedError, match="A"):
        cm.require_device()


def test_release_then_rediscover_starts_a_fresh_identity(monkeypatch) -> None:
    _patch_adb(monkeypatch, [("B", "device")])
    cm = ConnectionManager()

    cm.set_device_serial("A")
    assert cm.bound_serial == "A"

    # Device lost: the session binding is released...
    cm.release_serial_binding()
    assert cm.bound_serial is None

    # ...discovery may then observe the replacement device, ...
    assert cm.require_device() == "B"

    # ...and adopting it creates a NEW bound identity (never a mutation of A).
    cm.set_device_serial("B")
    assert cm.bound_serial == "B"


def test_same_bound_serial_behavior_is_unchanged(monkeypatch) -> None:
    fake = _patch_adb(monkeypatch, [("A", "device")])
    cm = ConnectionManager()
    cm.set_device_serial("A")

    for _ in range(3):
        assert cm.require_device() == "A"
        cm.shell(["echo", "hi"])

    assert _shell_target_serials(fake) == ["A"] * 3


def test_unpinned_single_device_autoselect_still_works(monkeypatch) -> None:
    fake = _patch_adb(monkeypatch, [("SOLO", "device")])
    cm = ConnectionManager()  # never bound: legacy discovery mode

    assert cm.require_device() == "SOLO"
    cm.shell(["getprop", "ro.product.manufacturer"])
    assert _shell_target_serials(fake) == ["SOLO"]


# --------------------------------------------------------------------------
# MonitorWorker: pin-on-connect / release-on-loss
# --------------------------------------------------------------------------

class _RecordingConnection:
    """CommandRunner stand-in that records binding lifecycle calls."""

    def __init__(self, serial: str = "A1") -> None:
        self.serial = serial
        self.pinned: list[str] = []
        self.release_count = 0
        self.shell_fail: BaseException | None = None

    def verify_available(self) -> None:
        pass

    def require_device(self) -> str:
        return self.serial

    def shell(self, args, timeout=None) -> str:
        if self.shell_fail is not None:
            raise self.shell_fail
        return ""

    def set_device_serial(self, serial: str) -> None:
        self.pinned.append(serial)

    def release_serial_binding(self) -> None:
        self.release_count += 1


@pytest.fixture
def qtapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_monitor_pins_discovered_serial_on_connect(qtapp) -> None:
    from android_task_manager.gui.monitor import MonitorWorker

    connection = _RecordingConnection(serial="A1")
    worker = MonitorWorker(connection=connection)
    seen: list[str] = []
    worker.serial_ready.connect(seen.append)

    worker._connect()

    assert worker._connected is True
    assert connection.pinned == ["A1"], "connect must bind the discovered serial"
    assert seen == ["A1"]


def test_monitor_releases_binding_when_device_lost_mid_session(qtapp) -> None:
    from android_task_manager.adb.exceptions import ADBDisconnectedError
    from android_task_manager.gui.monitor import MonitorWorker

    connection = _RecordingConnection(serial="A1")
    worker = MonitorWorker(connection=connection)
    worker._connect()
    assert worker._connected is True
    assert connection.release_count == 0

    # The bound device vanishes mid-session (any collector surfaces it).
    connection.shell_fail = ADBDisconnectedError("Device A1 is not present.")
    worker.tick()

    assert worker._connected is False
    assert connection.release_count >= 1, (
        "device loss must release the session binding"
    )
