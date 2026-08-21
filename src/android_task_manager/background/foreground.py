"""Parsing of the device's foreground-activity signal.

Reads the ``dumpsys activity activities`` text and extracts the resumed
(foreground) activity's package — the safest widely available signal for
"which app is the user looking at right now". The parser is pure and
fail-closed: anything unrecognizable yields an "unavailable" result, and
the caller must then treat every application's state as UNKNOWN rather
than pretending it is background.
"""

from __future__ import annotations

import re

from ..action.package import validate_package_name
from .models import ForegroundSnapshot

#: ``mResumedActivity: ActivityRecord{... u0 com.pkg/.MainActivity t42}``.
#: Older devices report the same record as ``mFocusedActivity``.
_RESUMED_RE = re.compile(
    r"m(?:Resumed|Focused)Activity:\s*ActivityRecord\{[^}]*?\bu(?P<user>\d+)\s+"
    r"(?P<package>[A-Za-z][A-Za-z0-9_.]*)/"
)


def parse_foreground_output(
    text: str, timestamp: float | None = None
) -> ForegroundSnapshot:
    """Extract the foreground package from ``dumpsys activity activities``.

    Returns ``available=False`` when no resumed/focused activity marker is
    found or the package does not survive strict validation — a malformed
    read must never become a foreground claim.
    """
    for line in text.splitlines():
        match = _RESUMED_RE.search(line)
        if match is None:
            continue
        candidate = match.group("package")
        try:
            package = validate_package_name(candidate)
        except ValueError:
            return ForegroundSnapshot(
                timestamp=timestamp if timestamp is not None else 0.0,
                package_name=None,
                available=False,
            )
        return ForegroundSnapshot(
            timestamp=timestamp if timestamp is not None else 0.0,
            package_name=package,
            available=True,
        )
    return ForegroundSnapshot(
        timestamp=timestamp if timestamp is not None else 0.0,
        package_name=None,
        available=False,
    )


__all__ = ["parse_foreground_output"]
