"""Normalized application inventory and detail models.

The inventory answers "what is installed on this device?" with the fields
``pm`` exposes in bulk: package name, APK path, UID, version code, and the
authoritative system/third-party classification from ``pm list packages``.
The detail model answers "what do I know about one application?" from one
``dumpsys package`` read.

Honesty rules follow the project convention: every field that a device
does not expose stays ``None`` (rendered as "N/A" by the GUI) — no value is
ever guessed or fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AppCategory(Enum):
    """System/User classification, with an honest unknown state.

    ``SYSTEM`` covers real system packages including updated system apps
    (``FLAG_UPDATED_SYSTEM_APP``): conservative classification keeps
    destructive controls away from anything Android considers a system
    package.
    """

    SYSTEM = "system"
    USER = "user"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AppInfo:
    """One installed application as reported by ``pm list packages``."""

    package_name: str
    #: Absolute APK path on the device (``None`` when not reported).
    apk_path: str | None = None
    uid: int | None = None
    version_code: int | None = None
    category: AppCategory = AppCategory.UNKNOWN
    #: ``False`` when the package is reported disabled by ``pm``.
    enabled: bool | None = None


@dataclass(frozen=True)
class ApplicationSnapshot:
    """A normalized view of the device's installed applications."""

    #: Monotonic timestamp of the sample.
    timestamp: float
    applications: list[AppInfo] = field(default_factory=list)


@dataclass(frozen=True)
class AppDetails:
    """One application's detail record from ``dumpsys package``.

    ``parse_complete`` is ``False`` when the raw text contained no
    recognizable package section (not installed, garbage, or an empty
    read) — callers can honestly say "could not verify" instead of
    presenting a plausible empty success.
    """

    package_name: str
    version_name: str | None = None
    version_code: int | None = None
    uid: int | None = None
    apk_path: str | None = None
    install_location: str | None = None
    category: AppCategory = AppCategory.UNKNOWN
    enabled: bool | None = None
    installer: str | None = None
    flags: tuple[str, ...] = ()
    launchable_activity: str | None = None
    activities: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    receivers: tuple[str, ...] = ()
    parse_complete: bool = False


__all__ = [
    "AppCategory",
    "AppDetails",
    "AppInfo",
    "ApplicationSnapshot",
]