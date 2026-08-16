"""Unit tests for the PermissionCollector (dumpsys package wrapper).

The real ADB layer is never touched: a scripted stub stands in for
``CommandRunner``. Collector behavior under test: correct command
construction, timeout propagation, timestamp stamping, and the
"collectors never swallow ADB failures" convention.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from android_task_manager.adb.exceptions import ADBTimeoutError
from android_task_manager.permissions import PermissionCollector
from android_task_manager.permissions.models import PERMISSION_INSTALL

PACKAGE_DUMP = """Package [com.example.app] (4f9a2c1):
    install permissions:
        android.permission.INTERNET: granted=true
    User 0:
        runtime permissions:
            android.permission.READ_SMS: granted=true, flags=[USER_SET]
"""


class StubRunner:
    """Minimal scripted stand-in for the CommandRunner protocol."""

    def __init__(self, response: str = "", error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[tuple[list[str], float | None]] = []

    def shell(self, args, timeout=None):
        self.calls.append((list(args), timeout))
        if self._error is not None:
            raise self._error
        return self._response


class TestCollect:
    def test_issues_dumpsys_package_for_the_requested_package(self):
        runner = StubRunner(response=PACKAGE_DUMP)
        PermissionCollector(runner).collect("com.example.app")
        assert runner.calls == [(["dumpsys", "package", "com.example.app"], None)]

    def test_timeout_is_propagated_to_the_runner(self):
        runner = StubRunner(response=PACKAGE_DUMP)
        PermissionCollector(runner, timeout=7.5).collect("com.example.app")
        assert runner.calls == [(["dumpsys", "package", "com.example.app"], 7.5)]

    def test_parses_the_raw_output_and_stamps_read_at(self):
        runner = StubRunner(response=PACKAGE_DUMP)
        audit = PermissionCollector(runner).collect("com.example.app")
        assert audit.package_name == "com.example.app"
        assert audit.parse_complete is True
        assert ("android.permission.INTERNET", True, PERMISSION_INSTALL) in {
            (e.name, e.granted, e.permission_type) for e in audit.permissions
        }
        assert isinstance(audit.read_at, datetime)
        assert audit.read_at.tzinfo is not None
        assert audit.read_at.tzinfo.utcoffset(None) == timezone.utc.utcoffset(None)

    def test_adb_failures_propagate_unswallowed(self):
        """The collector must not catch ADB errors (battery collector
        convention) — the caller decides how to present them."""
        runner = StubRunner(response="", error=ADBTimeoutError("dumpsys package", 5.0))
        with pytest.raises(ADBTimeoutError):
            PermissionCollector(runner).collect("com.example.app")
        assert runner.calls == [(["dumpsys", "package", "com.example.app"], None)]