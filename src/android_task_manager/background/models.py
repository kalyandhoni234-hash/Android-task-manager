"""Normalized models for background user-app intelligence.

Every field a source does not expose stays ``None`` (rendered as "N/A"
by the GUI) — no value is ever guessed or fabricated, following the
project-wide honesty convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class BackgroundAppState(Enum):
    """Whether an application is currently foreground or background.

    ``UNKNOWN`` is the honest default: only a successfully parsed
    foreground signal from the device may classify an application as
    BACKGROUND (or FOREGROUND). Without that evidence nothing is claimed.
    """

    FOREGROUND = "foreground"
    BACKGROUND = "background"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ForegroundSnapshot:
    """The device's currently resumed (foreground) activity package.

    ``available`` distinguishes "the read worked and this is the answer"
    (possibly ``None`` — e.g. the launcher) from "the foreground state
    could not be determined" (``available=False``): the GUI must render
    UNKNOWN states instead of pretending every running app is background.
    """

    timestamp: float
    #: Validated package name of the resumed activity, or ``None`` when the
    #: device reported no resumable activity.
    package_name: str | None = None
    #: ``False`` when the foreground state could not be determined.
    available: bool = False


@dataclass(frozen=True)
class BackgroundAppEntry:
    """One user application aggregated over its running processes.

    Built strictly from verified relationships: every process listed here
    was resolved to *package_name* through the authoritative installed-
    application inventory (UID match, then exact/prefixed process-name
    match). Processes without a verified owner never appear anywhere.
    """

    package_name: str
    #: Human-readable label resolved from the device (APK manifest), when
    #: available; ``None`` means "not resolved" and the GUI falls back to
    #: the package name. Never invented.
    label: str | None = None
    uid: int | None = None
    pids: tuple[int, ...] = ()
    #: Aggregated CPU percent across the app's processes (sum); ``None``
    #: when no process reported a CPU metric.
    cpu_percent: float | None = None
    #: Aggregated memory share (percent of total RAM) across processes;
    #: ``None`` when not determinable.
    memory_percent: float | None = None
    #: Aggregated absolute memory estimate in KiB derived from the memory
    #: snapshot's total and each process' percent share; ``None`` when the
    #: totals needed for the estimate were unavailable.
    memory_kb: int | None = None
    state: BackgroundAppState = BackgroundAppState.UNKNOWN
    #: Wall-clock time the application was last observed running.
    last_seen: datetime | None = None


@dataclass(frozen=True)
class BackgroundAppsSnapshot:
    """The aggregated per-application view at one moment."""

    timestamp: float
    entries: list[BackgroundAppEntry] = field(default_factory=list)

    def entry_for(self, package_name: str) -> BackgroundAppEntry | None:
        """The entry for *package_name*, or ``None``."""
        for entry in self.entries:
            if entry.package_name == package_name:
                return entry
        return None


__all__ = [
    "BackgroundAppEntry",
    "BackgroundAppsSnapshot",
    "BackgroundAppState",
    "ForegroundSnapshot",
]
