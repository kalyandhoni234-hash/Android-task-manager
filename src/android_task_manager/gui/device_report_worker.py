"""Worker that writes device-report exports off the GUI thread.

The payload is assembled on the GUI thread (pure dataclasses; no I/O);
only the JSON rendering + file write happen here, following the
IncidentWorker/BaselineWorker export conventions: duplicate requests while
one is in flight are dropped, and every attempt reports back through
``export_completed`` — never silently.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from ..core.diagnostics import log_unexpected_failure
from ..device_report.render import DeviceReportPayload, write_device_report


class DeviceReportWorker(QObject):
    """One-shot device-report file exports (JSON)."""

    #: (success, message) an export finished (or failed) — never silent
    export_completed = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self._export_busy = False

    # ------------------------------------------------------------------
    # Test/status accessors
    # ------------------------------------------------------------------

    def is_exporting(self) -> bool:
        """True while an export is being written."""
        return self._export_busy

    # ------------------------------------------------------------------
    # Synchronous operation (used by tests; the slot calls this)
    # ------------------------------------------------------------------

    def export_report(self, payload: DeviceReportPayload, path: str | Path) -> str:
        """Write *payload* to *path* as deterministic JSON; returns a
        human-readable confirmation message. Raises on write errors."""
        write_device_report(payload, path)
        return f"Exported device report to {path}."

    # ------------------------------------------------------------------
    # Slot (delivered onto this worker's thread by queued connections)
    # ------------------------------------------------------------------

    @Slot(str, object)
    def request_export(self, path: object, payload: object) -> None:
        """Write the device report off the GUI thread; always reports back."""
        if not isinstance(path, str) or not isinstance(payload, DeviceReportPayload):
            self.export_completed.emit(False, "The export was cancelled.")
            return
        if self._export_busy:
            return
        self._export_busy = True
        try:
            message = self.export_report(payload, path)
        except (OSError, ValueError) as exc:
            self.export_completed.emit(False, f"Export failed: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 - a worker bug never freezes the GUI
            log_unexpected_failure("device_report", "export", exc)
            self.export_completed.emit(False, "The export failed unexpectedly.")
            return
        finally:
            self._export_busy = False
        self.export_completed.emit(True, message)