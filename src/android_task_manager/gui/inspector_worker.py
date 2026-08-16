"""PDB worker that runs process inspections off the GUI thread.

The dashboard never inspects a process synchronously: selecting a row emits
``inspection_requested``, which (after a queued connection onto this object's
thread) reads the target's /proc<pid> files through ``ProcessInspector`` and
publishes either a normalized snapshot or a failure signal. GUI code never
calls into ADB itself.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from ..adb.connection import CommandRunner, ConnectionManager
from ..adb.exceptions import ADBError
from ..core.diagnostics import log_unexpected_failure
from ..process import ProcessDisappearedError, ProcessInspector


class ProcessInspectionWorker(QObject):
    """Runs one-shot, on-demand process inspections."""

    #: (ProcessInspectionSnapshot) a successful inspection result
    inspection_ready = Signal(object)
    #: (pid, human_message) the process disappeared or ADB failed
    inspection_failed = Signal(int, str)

    def __init__(
        self,
        connection: CommandRunner | None = None,
        adb_path: str = "adb",
        timeout: float = 10.0,
        device_serial: str | None = None,
    ) -> None:
        super().__init__()
        self._inspector = ProcessInspector(
            connection
            or ConnectionManager(adb_path=adb_path, timeout=timeout, device_serial=device_serial),
            timeout=timeout,
        )

    def inspect(self, pid: int):
        """Synchronous inspection (used by tests); raises on failure."""
        return self._inspector.sample(pid)

    @Slot(object)
    def request_inspect(self, pid: object) -> None:
        """Inspect *pid* and publish the result via signals.

        Runs on this worker's thread when connected through a queued signal;
        the dashboard stays responsive while the reads are in flight.
        """
        try:
            pid_int = int(str(pid))
        except (TypeError, ValueError):
            self.inspection_failed.emit(-1, f"invalid process id: {pid!r}")
            return
        try:
            snapshot = self._inspector.sample(pid_int)
        except (ADBError, ProcessDisappearedError) as exc:
            self.inspection_failed.emit(pid_int, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - collector bug never freezes GUI
            log_unexpected_failure("inspection", "sample", exc)
            self.inspection_failed.emit(pid_int, str(exc))
            return
        self.inspection_ready.emit(snapshot)