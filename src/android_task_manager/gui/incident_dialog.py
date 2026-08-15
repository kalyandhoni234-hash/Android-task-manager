"""Incident report viewer dialog: HTML preview plus export actions.

Read-only viewer: it renders the latest generated report with Qt's
rich-text engine (the same self-contained HTML the file export produces —
one source of truth), and forwards export requests to the MainWindow,
which owns the file dialogs and the off-thread writing.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..incident.models import IncidentReport
from ..incident.renderers import html_report


class IncidentDialog(QDialog):
    """Preview of the latest incident report."""

    #: ("json" | "html" | "pdf") the user asked to export the report.
    export_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Incident Report")
        self.resize(860, 640)

        self._title = QLabel("")
        self._title.setObjectName("incidentDialogTitle")
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setWordWrap(True)

        self._view = QTextBrowser()
        self._view.setOpenExternalLinks(False)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._json_btn = QPushButton("Export JSON")
        self._html_btn = QPushButton("Export HTML")
        self._pdf_btn = QPushButton("Export PDF")
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primary")
        buttons.addWidget(self._json_btn)
        buttons.addWidget(self._html_btn)
        buttons.addWidget(self._pdf_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        self._status = QLabel("")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(self._view, 1)
        layout.addLayout(buttons)
        layout.addWidget(self._status)

        self._json_btn.clicked.connect(lambda: self.export_requested.emit("json"))
        self._html_btn.clicked.connect(lambda: self.export_requested.emit("html"))
        self._pdf_btn.clicked.connect(lambda: self.export_requested.emit("pdf"))
        close_btn.clicked.connect(self.accept)

        self._exporting = False
        self._report: IncidentReport | None = None
        self._refresh_buttons()

    # ------------------------------------------------------------------
    # State entry points (MainWindow calls these on the GUI thread)
    # ------------------------------------------------------------------

    def show_report(self, report: IncidentReport) -> None:
        """Render *report* in the viewer and reset export state."""
        self._exporting = False
        self._report = report
        self._title.setText(
            f"{report.metadata.report_id} — {report.severity_summary.assessment} "
            f"({report.severity_summary.total} finding(s))"
        )
        self._view.setHtml(html_report(report))
        self._status.setText("")
        self._refresh_buttons()

    def set_export_busy(self, busy: bool) -> None:
        self._exporting = busy
        self._refresh_buttons()
        if busy:
            self._status.setText("Exporting…")

    def show_export_result(self, success: bool, message: str) -> None:
        self._exporting = False
        self._status.setText(message)
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        enabled = self._report is not None and not self._exporting
        self._json_btn.setEnabled(enabled)
        self._html_btn.setEnabled(enabled)
        self._pdf_btn.setEnabled(enabled)