"""Storage collector: samples the internal shared volume (``/data``).

Runs through the shared ``CommandRunner`` — the same ADB facade every
other collector uses; this module never touches ``subprocess``. Parsing
reuses the device-information parsers (``parse_df_k`` +
``pick_internal_storage``): there is exactly one df parser in the project.

Failure semantics (explicit, never fabricated):

- An ADB-level failure (device lost, timeout, permission-denied shell
  error) raises the same typed ``ADBError`` as the other collectors, so
  the monitor's connection handling reacts correctly.
- Output that simply does not contain a usable volume (empty ``df``
  output, missing ``/data`` row, malformed numbers) returns ``None``: the
  metric is *unavailable*, not a device problem. The monitor stores None,
  publishes an explicit unavailable state, and retries on the next
  interval — one unreadable metric never fails the whole pipeline.
"""

from __future__ import annotations

import time

from ..adb.connection import CommandRunner
from ..device.parser import parse_df_k, pick_internal_storage
from .models import StorageSnapshot


class StorageCollector:
    """Samples the internal storage volume (``df -k /data``)."""

    def __init__(self, runner: CommandRunner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def sample(self) -> StorageSnapshot | None:
        """Read one live storage snapshot, or None when unavailable."""
        text = self._runner.shell(["df", "-k", "/data"], timeout=self._timeout)
        volume = pick_internal_storage(parse_df_k(text))
        if volume is None:
            return None
        return StorageSnapshot(
            timestamp=time.monotonic(),
            mount=volume.mount,
            total_kb=volume.total_kb,
            used_kb=volume.used_kb,
            available_kb=volume.available_kb,
        )
