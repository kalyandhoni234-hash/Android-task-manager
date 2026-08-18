"""Application inventory and detail collector.

Reads the installed-application facts through the shared
:class:`~android_task_manager.adb.connection.CommandRunner` — never
``subprocess`` directly — and hands raw text to the pure parsers in
``parser.py``. The collector contains no parsing logic.

The inventory uses four ``pm list packages`` reads (file/UID/versioncode,
system, third-party, disabled) — each a single bounded subprocess — while
details use one ``dumpsys package <pkg>`` read. A failed read surfaces as
the typed ADB exception, leaving the caller (a worker/GUI layer) to decide
how to present it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..adb.connection import CommandRunner
from .models import AppDetails, ApplicationSnapshot
from .parser import build_inventory, parse_app_details


class ApplicationCollector:
    """Samples the device's installed applications via ``pm`` reads."""

    def __init__(self, runner: CommandRunner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def collect(self, timestamp: float | None = None) -> ApplicationSnapshot:
        """Read and normalize the installed-application inventory.

        Raises the typed ADB exceptions on device/connection failure (the
        existing collector convention); parsing is delegated entirely to
        the pure parser.
        """
        inventory = self._runner.shell(
            ["pm", "list", "packages", "-f", "-U", "--show-versioncode"],
            timeout=self._timeout,
        )
        system = self._runner.shell(
            ["pm", "list", "packages", "-s"],
            timeout=self._timeout,
        )
        user = self._runner.shell(
            ["pm", "list", "packages", "-3"],
            timeout=self._timeout,
        )
        disabled = self._runner.shell(
            ["pm", "list", "packages", "-d"],
            timeout=self._timeout,
        )
        apps = build_inventory(
            inventory,
            system_text=system,
            user_text=user,
            disabled_text=disabled,
        )
        return ApplicationSnapshot(
            timestamp=timestamp or datetime.now(timezone.utc).timestamp(),
            applications=apps,
        )

    def collect_details(self, package_name: str) -> AppDetails:
        """Read and normalize one package's detail record.

        Raises the typed ADB exceptions on device/connection failure; a
        not-installed package produces a ``parse_complete=False`` record
        instead of a fabricated one.
        """
        text = self._runner.shell(
            ["dumpsys", "package", package_name],
            timeout=self._timeout,
        )
        return parse_app_details(text, package_name)


__all__ = ["ApplicationCollector"]