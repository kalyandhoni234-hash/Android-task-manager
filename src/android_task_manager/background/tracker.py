"""Bounded last-seen annotation for background-app entries.

A tiny presentation-layer tracker: it remembers when each application
was last observed running and stamps entries accordingly. It is owned
by the window layer, cleared on every disconnect, and never survives a
reconnect — stale observations must never be presented as current.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .models import BackgroundAppEntry, BackgroundAppsSnapshot


class LastSeenTracker:
    """Annotates a snapshot's entries with their last-seen wall time."""

    def __init__(self) -> None:
        self._seen: dict[str, datetime] = {}

    def __len__(self) -> int:
        return len(self._seen)

    def clear(self) -> None:
        """Forget every observation (device disconnect / new session)."""
        self._seen.clear()

    def annotate(
        self,
        snapshot: BackgroundAppsSnapshot,
        now: datetime | None,
    ) -> BackgroundAppsSnapshot:
        """Return *snapshot* with ``last_seen`` stamped on each entry.

        ``now`` is the wall-clock moment of this observation; ``None``
        clears the stamps (used after :meth:`clear` to prove nothing is
        carried over).
        """
        if now is not None:
            for entry in snapshot.entries:
                self._seen[entry.package_name] = now
        annotated: list[BackgroundAppEntry] = []
        for entry in snapshot.entries:
            last_seen = self._seen.get(entry.package_name)
            if entry.last_seen != last_seen:
                entry = replace(entry, last_seen=last_seen)
            annotated.append(entry)
        return BackgroundAppsSnapshot(timestamp=snapshot.timestamp, entries=annotated)


__all__ = ["LastSeenTracker"]
