"""Normalized storage data models.

``StorageSnapshot`` is the contract between the storage collector and the
GUI: one live read of the internal shared volume (``/data``), in 1 KiB
blocks exactly as ``df -k`` reports them. ``None`` fields never appear in
this model — a volume that cannot be read is signaled by the collector
returning no snapshot at all (see ``collector.py``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StorageSnapshot:
    """A live view of the internal storage volume at one moment."""

    #: Monotonic timestamp of the sample.
    timestamp: float
    #: The mount point this volume represents, e.g. ``/data``.
    mount: str
    #: Total space in 1 KiB blocks.
    total_kb: int
    #: Used space in 1 KiB blocks.
    used_kb: int
    #: Available space in 1 KiB blocks.
    available_kb: int

    @property
    def used_percent(self) -> float | None:
        """Used share of total, or None when total is not positive."""
        if self.total_kb <= 0:
            return None
        return self.used_kb / self.total_kb * 100
