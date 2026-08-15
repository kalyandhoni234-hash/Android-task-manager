"""Worker that writes incident-report exports off the GUI thread.

Report *generation* is a pure in-memory function and runs on the GUI
thread (it is fast and deterministic); only the file writes (JSON/HTML/PDF)
happen here, following the BaselineWorker's export conventions: duplicate
requests while one is in flight are dropped, and every attempt reports
back through ``export_completed`` — never silently.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from ..incident.renderers import write_html_report, write_json_report
from .incident_pdf import write_incident_pdf

_JSON = "json"
_HTML = "html"
_PDF = "pdf"


class IncidentWorker(QObject):
    """One-shot incident-report file exports (JSON / HTML / PDF)."""

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

    def export_report(self, report, kind: str, path: str | Path) -> str:
        """Write *report* to *path* in the requested format; returns a
        human-readable confirmation message. Raises on write errors."""
        if kind == _JSON:
            write_json_report(report, path)
            return f"Exported incident report JSON to {path}."
        if kind == _HTML:
            write_html_report(report, path)
            return f"Exported incident report HTML to {path}."
        if kind == _PDF:
            write_incident_pdf(report, path)
            return f"Exported incident report PDF to {path}."
        raise ValueError(f"unsupported export format: {kind!r}")

    # ------------------------------------------------------------------
    # Slot (delivered onto this worker's thread by queued connections)
    # ------------------------------------------------------------------

    @Slot(str, str, object)
    def request_export(self, kind: object, path: object, report: object) -> None:
        """Write the report export off the GUI thread; always reports back."""
        if not isinstance(kind, str) or not isinstance(path, str):
            self.export_completed.emit(False, "The export was cancelled.")
            return
        if self._export_busy:
            return
        self._export_busy = True
        try:
            message = self.export_report(report, kind, path)
        except (OSError, ValueError) as exc:
            self.export_completed.emit(False, f"Export failed: {exc}")
            return
        except Exception:  # noqa: BLE001 - a worker bug never freezes the GUI
            self.export_completed.emit(False, "The export failed unexpectedly.")
            return
        finally:
            self._export_busy = False
        self.export_completed.emit(True, message)