"""Read-only process inspector: reads /proc/<pid> over the ADB runner.

This collector never spawns Python-level child processes; every read goes
through the injected runner (normally ``ConnectionManager``) with safe
argument lists and the existing timeout behavior. PIDs are validated before a
path is built.

Read failures are handled per explicit rules:

* ``No such file or directory`` on status/stat/cmdline → the process exited:
  a :class:`ProcessDisappearedError` is raised so the UI can show a clean
  "no longer available" state.
* ``Permission denied`` (or any other) error on status/stat/cmdline → the
  relevant fields are reported as unavailable (``None``), not fabricated.
* ``/proc/<pid>/io`` failure of *any* kind → ``io_read_bytes`` / ``io_write_bytes``
  become ``None``. This file is optional and commonly permission-protected.
"""

from __future__ import annotations

import time

from ..adb.exceptions import ADBCommandError, ADBError
from . import inspector_parser as _parser
from .inspector_models import ProcessInspectionSnapshot
from .inspector_parser import StatParseError

#: Android (arm/arm64) page size used only for the stat ``rss`` fallback.
_PAGE_SIZE_KIB = 4


class ProcessInspectionError(RuntimeError):
    """Base for process-inspection specific errors."""


class ProcessDisappearedError(ProcessInspectionError):
    """The inspected process exited before its /proc data could be read."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        super().__init__(f"Process {pid} exited before inspection completed.")


def _validate_pid(pid: int) -> None:
    """Reject non-integer or obviously invalid PIDs before building paths."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError(f"invalid PID: {pid!r}")


class ProcessInspector:
    """Inspects a single PID by reading its /proc/<pid> files."""

    def __init__(self, runner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def sample(self, pid: int, process_info=None) -> ProcessInspectionSnapshot:
        """Read and assemble one normalized inspection snapshot.

        :param pid: Target process ID (validated before any path is built).
        :param process_info: Optional existing
            ``ProcessInfo`` whose ``cpu_percent``/``memory_percent`` are copied
            so only one CPU calculation exists in the codebase.
        """
        _validate_pid(pid)
        path = f"/proc/{pid}"

        status_text = self._read_optional(f"{path}/status", pid)
        stat_text = self._read_optional(f"{path}/stat", pid)
        cmdline_text = self._read_optional(f"{path}/cmdline", pid)

        status = _parser.parse_status(status_text or "")
        try:
            stat = _parser.parse_stat(stat_text or "")
        except StatParseError:
            stat = _parser.StatFields()

        command_line = _parser.parse_cmdline(cmdline_text or "")

        io_read_bytes = None
        io_write_bytes = None
        try:
            io_text = self._runner.shell(["cat", f"{path}/io"], timeout=self._timeout)
            io_read_bytes, io_write_bytes = _parser.parse_io(io_text)
        except ADBError:
            pass  # io is optional; permission issues render fields unavailable.

        name = status.name or stat.name
        uid = status.uid
        state = status.state or stat.state
        threads = status.threads if status.threads is not None else stat.num_threads

        virtual_memory_kb = status.vm_size_kb
        if virtual_memory_kb is None and stat.vsize_bytes is not None:
            virtual_memory_kb = stat.vsize_bytes // 1024

        resident_memory_kb = status.vm_rss_kb
        if resident_memory_kb is None and stat.rss_pages is not None:
            resident_memory_kb = stat.rss_pages * _PAGE_SIZE_KIB

        return ProcessInspectionSnapshot(
            pid=pid,
            name=name,
            uid=uid,
            state=state,
            threads=threads,
            priority=stat.priority,
            nice=stat.nice,
            virtual_memory_kb=virtual_memory_kb,
            resident_memory_kb=resident_memory_kb,
            rss_anon_kb=status.rss_anon_kb,
            rss_file_kb=status.rss_file_kb,
            shared_memory_kb=status.rss_shmem_kb,
            command_line=command_line,
            cpu_percent=process_info.cpu_percent if process_info else None,
            memory_percent=process_info.memory_percent if process_info else None,
            io_read_bytes=io_read_bytes,
            io_write_bytes=io_write_bytes,
            timestamp=time.monotonic(),
        )

    def _read_optional(self, path: str, pid: int) -> str | None:
        """Read one identity file, mapping failures to None / disappearance."""
        try:
            return self._runner.shell(["cat", path], timeout=self._timeout)
        except ADBCommandError as exc:
            stderr = (exc.stderr or "").lower()
            if "no such file or directory" in stderr:
                raise ProcessDisappearedError(pid) from exc
            if "permission denied" in stderr:
                return None
            raise
        except ADBError:
            raise