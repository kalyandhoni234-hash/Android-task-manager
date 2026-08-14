"""Battery collector: drives ``dumpsys battery`` through the ADB layer.

Same pattern as the other collectors: consumes the shared ``CommandRunner``
(ConnectionManager), never touches subprocess, and returns a normalized
``BatterySnapshot`` with a monotonic timestamp.
"""

from __future__ import annotations

import time

from ..adb.connection import CommandRunner
from .models import BatterySnapshot
from .parser import parse_battery_output


class BatteryCollector:
    """Samples the device battery service via ``dumpsys battery``."""

    def __init__(self, runner: CommandRunner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def sample(self) -> BatterySnapshot:
        """Read and normalize one battery snapshot."""
        text = self._runner.shell(["dumpsys", "battery"], timeout=self._timeout)
        return parse_battery_output(text, timestamp=time.monotonic())