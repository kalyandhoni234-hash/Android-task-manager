"""Device information: structured identity, hardware, software, display,
storage and identifier facts collected through the shared ADB layer.

Only structured, collected data leaves this package — the GUI never parses
device output itself. See ``models.DeviceInformation`` for the field
contract and ``collector.DeviceInfoCollector`` for the read rules.
"""

from __future__ import annotations

from .collector import DeviceInfoCollector
from .models import DeviceInformation, StorageInfo

__all__ = ["DeviceInfoCollector", "DeviceInformation", "StorageInfo"]