"""Incident reporting panel: generate, view and export investigation reports.

Read-only presentation view, following the Baseline & Security panel's
conventions. The panel itself only emits requests and renders results:

* "Generate Report" is disabled until a drift check ran (the report is an
  investigation artifact of a session — no session, no report). Generation
  itself is a pure in-memory build and runs on the GUI thread.
* "View Report" and the export buttons are disabled until a report exists.
* Every button is disabled while an export is in flight; completed exports
  always leave a visible status message (success or failure).

The summary line always states real counts (including 0s) and the honest
assessment wording from the report itself.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ...incident.models import IncidentReport
from . import panel_host


class IncidentPanel(QWidget):
    """The Incident Reporting feature area of the dashboard."""

    #: The user asked to generate a report from the current session data.
    generate_requested = Signal()
    #: The user asked to open the report viewer dialog.
    view_requested = Signal()
    #: ("json" | "html" | "pdf") the user asked to export the last report.
    export_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "INCIDENT REPORTING")

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        self._generate_btn = self._make_button(
            "Generate Report", "generateReportBtn", primary=True
        )
        self._view_btn = self._make_button("View Report", "viewReportBtn")
        actions_row.addWidget(self._generate_btn)
        actions_row.addWidget(self._view_btn)
        actions_row.addStretch(1)
        layout.addLayout(actions_row)

        self._report_label = QLabel("No report generated yet")
        self._report_label.setObjectName("incidentSummary")
        self._report_label.setTextFormat(Qt.TextFormat.PlainText)
        self._report_label.setWordWrap(True)
        layout.addWidget(self._report_label)

        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        self._json_btn = self._make_button("Export JSON", "incidentExportJsonBtn")
        self._html_btn = self._make_button("Export HTML", "incidentExportHtmlBtn")
        self._pdf_btn = self._make_button("Export PDF", "incidentExportPdfBtn")
        export_row.addWidget(self._json_btn)
        export_row.addWidget(self._html_btn)
        export_row.addWidget(self._pdf_btn)
        export_row.addStretch(1)
        layout.addLayout(export_row)

        self._status = QLabel("")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._generate_btn.clicked.connect(self._on_generate_clicked)
        self._view_btn.clicked.connect(self._on_view_clicked)
        self._json_btn.clicked.connect(lambda: self._on_export_clicked("json"))
        self._html_btn.clicked.connect(lambda: self._on_export_clicked("html"))
        self._pdf_btn.clicked.connect(lambda: self._on_export_clicked("pdf"))

        self._report: IncidentReport | None = None
        self._generating = False
        self._exporting = False
        self._generation_available = False
        self._refresh_buttons()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _make_button(self, text: str, name: str, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("primary" if primary else "secondary")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button

    # ------------------------------------------------------------------
    # State entry points (MainWindow calls these on the GUI thread)
    # ------------------------------------------------------------------

    def set_report(self, report: IncidentReport | None) -> None:
        """Adopt a generated report (or clear it)."""
        self._generating = False
        self._exporting = False
        self._report = report
        if report is None:
            self._report_label.setText("No report generated yet")
        else:
            summary = report.severity_summary
            self._report_label.setText(
                f"Report {report.metadata.report_id} — {summary.assessment} "
                f"({summary.total} finding(s): {summary.high} HIGH, "
                f"{summary.medium} MEDIUM, {summary.info} INFO)"
            )
        self._refresh_buttons()

    def set_generation_available(self, available: bool) -> None:
        """Whether a report can be generated (a drift check has run)."""
        self._generation_available = available
        self._refresh_buttons()

    def set_generating(self, busy: bool) -> None:
        self._generating = busy
        self._refresh_buttons()
        if busy:
            self._show_status("Generating report…")

    def set_export_busy(self, busy: bool) -> None:
        self._exporting = busy
        self._refresh_buttons()
        if busy:
            self._show_status("Exporting…")

    def show_export_result(self, success: bool, message: str) -> None:
        self._exporting = False
        self._generating = False
        self._show_status(message, warn=not success)
        self._refresh_buttons()

    def show_export_cancelled(self) -> None:
        self._show_status("Export cancelled.")

    def _show_status(self, text: str, warn: bool = False) -> None:
        self._status.setText(text)
        self._status.setObjectName("statusWarn" if warn else "muted")
        style = self._status.style()
        style.unpolish(self._status)
        style.polish(self._status)

    # ------------------------------------------------------------------
    # Click handlers + button policy
    # ------------------------------------------------------------------

    def _on_generate_clicked(self) -> None:
        if self._generating or self._exporting:
            return
        self.generate_requested.emit()

    def _on_view_clicked(self) -> None:
        if self._generating or self._exporting or self._report is None:
            return
        self.view_requested.emit()

    def _on_export_clicked(self, kind: str) -> None:
        if self._generating or self._exporting or self._report is None:
            return
        self.export_requested.emit(kind)

    def _refresh_buttons(self) -> None:
        busy = self._generating or self._exporting
        self._generate_btn.setEnabled(self._generation_available and not busy)
        self._view_btn.setEnabled(self._report is not None and not busy)
        self._json_btn.setEnabled(self._report is not None and not busy)
        self._html_btn.setEnabled(self._report is not None and not busy)
        self._pdf_btn.setEnabled(self._report is not None and not busy)