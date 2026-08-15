"""Update checker: compares the running version against the latest GitHub release.

The check is a single network call per app launch, performed on a
background worker thread; this module never downloads or installs anything.
"""

from __future__ import annotations

from .check import (
    VersionParseError,
    check_for_update,
    fetch_latest_release_tag,
    is_newer,
    parse_version,
)
from .models import UpdateCheckResult

__all__ = [
    "UpdateCheckResult",
    "VersionParseError",
    "check_for_update",
    "fetch_latest_release_tag",
    "is_newer",
    "parse_version",
]