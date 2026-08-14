"""Typed, normalized snapshot for the read-only process inspector.

Field semantics (and where each value comes from):

``/proc/<pid>/status``
    * ``Name`` → ``name`` (fallback: stat comm)
    * ``State`` → ``state`` (Android can report e.g. ``S (sleeping)``)
    * ``Uid``   → ``uid`` (real UID = first of the four whitespace values)
    * ``Threads`` → ``threads`` (fallback: stat num_threads)
    * ``VmSize``  → ``virtual_memory_kb`` (kB)
    * ``VmRSS``   → ``resident_memory_kb`` (kB)
    * ``RssAnon`` → ``rss_anon_kb`` (kB)
    * ``RssFile`` → ``rss_file_kb`` (kB)
    * ``RssShmem``→ ``shared_memory_kb`` (kB)

``/proc/<pid>/stat``
    * field 18 ``priority`` → ``priority`` (scheduling priority)
    * field 19 ``nice``    → ``nice``
    * field 20 ``num_threads`` → fallback ``threads``
    * field 23 ``vsize``   → fallback ``virtual_memory_kb`` (bytes // 1024)
    * field 24 ``rss``     → fallback ``resident_memory_kb`` (pages × 4 KiB)

``/proc/<pid>/cmdline`` (NUL-separated) ``→ command_line`` (spaces joined).

``/proc/<pid>/io`` ``read_bytes``/``write_bytes`` → ``io_read_bytes`` / ``io_write_bytes``.

Memory semantics (documented, not decorative):

* **Virtual Memory** is ``VmSize`` — the process's virtual address space size.
* **Resident Memory** is ``VmRSS`` — physical pages currently mapped in RAM.
  It is not "total RAM the app owns" and it is definitely not PSS
  (proportional set size), which this milestone does not compute. RSS may
  double-count pages shared with other processes.
* **Shared Memory** is ``RssShmem`` only — the shared part of RSS. It is not
  SysV shared memory (``VmShm``).

``cpu_percent`` / ``memory_percent`` are **not** (re)computed here to avoid a
second CPU calculation; they are copied from the matching entry of the
existing :class:`~android_task_manager.process.models.ProcessInfo` and applied
onto the snapshot at association time.

Any field the device will not expose is ``None`` ("unavailable") — never a
fabricated zero.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessInspectionSnapshot:
    """A single read-only inspection of one process' /proc/<pid> files."""

    pid: int
    name: str | None = None
    uid: int | None = None
    state: str | None = None
    threads: int | None = None
    priority: int | None = None
    nice: int | None = None
    virtual_memory_kb: int | None = None
    resident_memory_kb: int | None = None
    rss_anon_kb: int | None = None
    rss_file_kb: int | None = None
    shared_memory_kb: int | None = None
    command_line: str | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None
    io_read_bytes: int | None = None
    io_write_bytes: int | None = None
    timestamp: float = 0.0