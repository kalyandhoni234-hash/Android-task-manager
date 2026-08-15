"""Update-checker data model (frozen, typed, GUI-thread-safe)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UpdateCheckResult:
    """Outcome of one update check against the GitHub release feed.

    ``latest_version`` / ``release_url`` are ``None`` whenever the check
    failed for any reason — a version is never fabricated. ``error`` holds
    a short human-readable reason on failure and is ``None`` otherwise.
    """

    checked_at: datetime
    current_version: str
    latest_version: str | None = None
    update_available: bool = False
    release_url: str | None = None
    error: str | None = None