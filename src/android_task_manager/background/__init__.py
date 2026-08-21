"""Background user-app intelligence (v0.8.x).

Connects the existing PROCESS pipeline to the existing APPLICATION
inventory so the Intelligence page can answer one question clearly:

    "Which installed user apps are currently running in the background,
     and how much CPU/RAM are they using?"

The module is pure: it consumes the snapshots the monitor already
publishes (``ProcessSnapshot``, ``ApplicationSnapshot``, ``MemorySnapshot``)
plus a foreground-app signal, and produces an aggregated per-application
view. It never talks to ADB, owns no timers, and fabricates nothing.
"""

from __future__ import annotations

from .builder import build_background_apps
from .collector import ForegroundCollector
from .foreground import parse_foreground_output
from .models import (
    BackgroundAppEntry,
    BackgroundAppsSnapshot,
    ForegroundSnapshot,
)
from .tracker import LastSeenTracker

__all__ = [
    "BackgroundAppEntry",
    "BackgroundAppsSnapshot",
    "ForegroundCollector",
    "ForegroundSnapshot",
    "LastSeenTracker",
    "build_background_apps",
    "parse_foreground_output",
]
