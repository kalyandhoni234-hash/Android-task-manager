"""Memory collector: drives ADB reads and produces normalized memory snapshots.

Uses the shared ``CommandRunner`` interface (satisfied by ConnectionManager);
this module never calls ``subprocess`` directly.
"""

from __future__ import annotations

import time

from ..adb.connection import CommandRunner
from .models import MemorySnapshot
from .parser import parse_meminfo


class MemoryCollector:
    """Samples /proc/meminfo on the target device."""

    def __init__(self, runner: CommandRunner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def sample(self) -> MemorySnapshot:
        """Read and normalize one /proc/meminfo snapshot."""
        text = self._runner.shell(["cat", "/proc/meminfo"], timeout=self._timeout)
        values = parse_meminfo(text)
        return MemorySnapshot(timestamp=time.monotonic(), **values)