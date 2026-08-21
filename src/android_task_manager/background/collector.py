"""Foreground-activity collector.

Reads the device's resumed-activity signal through the shared
:class:`~android_task_manager.adb.connection.CommandRunner` — never
``subprocess`` directly — and hands the raw text to the pure parser in
``foreground.py``. The collector contains no parsing logic, mirroring the
other collectors' conventions.
"""

from __future__ import annotations

import time

from ..adb.connection import CommandRunner
from .foreground import parse_foreground_output
from .models import ForegroundSnapshot


class ForegroundCollector:
    """Samples which application is currently in the foreground."""

    def __init__(self, runner: CommandRunner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def sample(self) -> ForegroundSnapshot:
        """Read and normalize the foreground-activity signal.

        Raises the typed ADB exceptions on device/connection failure (the
        existing collector convention); an unparseable read yields an
        ``available=False`` snapshot instead of a foreground claim.
        """
        text = self._runner.shell(
            ["dumpsys", "activity", "activities"],
            timeout=self._timeout,
        )
        return parse_foreground_output(text, timestamp=time.monotonic())


__all__ = ["ForegroundCollector"]
