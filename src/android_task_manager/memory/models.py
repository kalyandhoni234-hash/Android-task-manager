"""Normalized memory data models.

The MemorySnapshot is the contract between the memory parser, collector and the
terminal renderer. Raw adb/proc output never reaches the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemorySnapshot:
    """A normalized view of the device's RAM at one moment.

    All values are in KiB (1024-byte units) as reported by ``/proc/meminfo``.
    """

    #: Monotonic timestamp of the sample.
    timestamp: float
    #: MemTotal — physical RAM installed on the device.
    total_kb: int
    #: MemFree — permanently unallocated pages.
    free_kb: int
    #: MemAvailable — memory that can be handed to a new allocation without
    #: swapping, counting readily-reclaimable cache. This is the primary
    #: indicator of memory pressure on Linux/Android.
    available_kb: int
    #: Buffers — memory used as buffers (block device I/O caches).
    buffers_kb: int
    #: Cached — page cache (file-backed memory), including tmpfs/shmem portions.
    cached_kb: int
    #: SwapCached — anonymous pages evicted to swap that are still in the cache.
    swap_cached_kb: int

    @property
    def used_kb(self) -> int:
        """Memory that is not available for new allocations.

        Formula: ``used_kb = total_kb - available_kb``.

        This is intentionally NOT ``total - free``: ``MemFree`` ignores the
        large amount of memory Linux keeps as reclaimable page cache, so it
        under-reports what is genuinely free. ``MemAvailable`` is the kernel's
        own estimate of how much memory can be committed, so subtracting it
        from ``MemTotal`` is the least misleading single "in use" number this
        snapshot exposes.

        Treat this as a pressure baseline, not as a claim about maximally
        reclaimable memory. Prefer ``available_kb`` for "how much is free to
        use" messaging.
        """
        return self.total_kb - self.available_kb