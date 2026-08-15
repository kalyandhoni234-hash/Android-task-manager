"""Package/permission audit collector.

Reads one package's granted permissions via ``dumpsys package <pkg>``
through the shared :class:`~android_task_manager.adb.connection.CommandRunner`
(ConnectionManager) — never ``subprocess`` directly — and hands the raw text
to the pure parser in ``parser.py``. The collector contains no parsing logic.

Failure convention matches the other collectors (e.g. ``BatteryCollector``):
a failed/timed-out/unreadable ADB call surfaces as the typed ADB exception,
leaving the caller (a future GUI/worker layer) to decide how to present it.
A package that is not installed needs no pre-validation here — ``dumpsys``
itself returns a not-found style message, which the parser's no-recognizable-
section fallback turns into an honest ``parse_complete=False`` audit.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..adb.connection import CommandRunner
from .models import PackagePermissionAudit
from .parser import parse_dumpsys_package


class PermissionCollector:
    """Samples one package's permission state via ``dumpsys package``."""

    def __init__(self, runner: CommandRunner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def collect(self, package_name: str) -> PackagePermissionAudit:
        """Read and normalize one package's granted permissions.

        Raises the typed ADB exceptions on device/connection failure (the
        existing collector convention); parsing is delegated entirely to
        :func:`parse_dumpsys_package`.
        """
        text = self._runner.shell(
            ["dumpsys", "package", package_name],
            timeout=self._timeout,
        )
        return parse_dumpsys_package(
            text,
            package_name,
            read_at=datetime.now(timezone.utc),
        )