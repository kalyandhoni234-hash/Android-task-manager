"""Baseline & Security panel: baseline capture, drift check, export, signals.

Read-only presentation view: it holds a ``BaselineSnapshot`` and the latest
``DriftReport`` + ``HeuristicReport`` in GUI-layer memory (persistence is
still deferred), renders them, and emits *requests* — the actual device
reads / diffs / file writes run on the BaselineWorker's thread.

Button laws (honesty, no stacking):

* "Check Drift" is disabled with no baseline set — it has nothing to
  compare against.
* "Export JSON"/"Export CSV" are disabled until a drift check ran — there
  is no report to export yet.
* Every button is disabled while any operation is in flight; completed
  operations always leave a visible status message (success or failure).

Honest rendering: the drift summary always states the count (including
0), an unverified-categories note is never hidden, the signals section
explicitly says "not checked yet" / "no signals, N rules checked", and
severity colors reuse the existing GUI palette (MEDIUM = amber
``level=elevated``, HIGH = red ``level=high``).
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...baseline import BaselineSnapshot, DriftReport
from ...heuristics import SEVERITY_HIGH, SEVERITY_MEDIUM, HeuristicReport
from . import panel_host


def _fmt_when(value: datetime) -> str:
    """Local-time, second-resolution timestamp for the header rows."""
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


class BaselinePanel(QWidget):
    """The Baseline & Security feature area of the dashboard."""

    #: The user asked to capture a fresh baseline.
    save_requested = Signal()
    #: (BaselineSnapshot) the user asked to check drift against this baseline.
    check_requested = Signal(object)
    #: ("json" | "csv") the user asked to export the last session.
    export_requested = Signal(str)
    #: The user asked to open the investigation timeline dialog.
    timeline_requested = Signal()
    #: The user asked to open the process-tree dialog.
    process_tree_requested = Signal()
    #: (SuspiciousSignal) the user asked "why was this flagged?" for a signal.
    why_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "BASELINE & SECURITY")

        header_row = QHBoxLayout()
        header_row.setSpacing(18)
        self._baseline_label = QLabel("Baseline: Not set")
        self._baseline_label.setObjectName("baselineHeader")
        self._baseline_label.setTextFormat(Qt.TextFormat.PlainText)
        self._baseline_label.setWordWrap(True)
        header_row.addWidget(self._baseline_label, 1)
        self._checked_label = QLabel("Last checked: —")
        self._checked_label.setObjectName("checkedHeader")
        self._checked_label.setTextFormat(Qt.TextFormat.PlainText)
        self._checked_label.setWordWrap(True)
        header_row.addWidget(self._checked_label)
        layout.addLayout(header_row)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        self._save_btn = self._make_button("Save Baseline", "saveBaselineBtn", primary=True)
        self._check_btn = self._make_button("Check Drift", "checkDriftBtn")
        actions_row.addWidget(self._save_btn)
        actions_row.addWidget(self._check_btn)
        actions_row.addStretch(1)
        layout.addLayout(actions_row)

        self._drift_summary = QLabel("No drift check yet")
        self._drift_summary.setObjectName("driftSummary")
        self._drift_summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._drift_summary)

        self._unverified = QLabel("")
        self._unverified.setObjectName("statusWarn")
        self._unverified.setWordWrap(True)
        self._unverified.hide()
        layout.addWidget(self._unverified)

        signals_title = QLabel("SUSPICIOUS SIGNALS")
        signals_title.setObjectName("sectionTitle")
        layout.addWidget(signals_title)

        self._signals_box = QWidget()
        self._signals_layout = QVBoxLayout(self._signals_box)
        self._signals_layout.setContentsMargins(0, 0, 0, 0)
        self._signals_layout.setSpacing(4)
        self._no_signals = QLabel("Not checked yet")
        self._no_signals.setObjectName("noSignals")
        self._no_signals.setTextFormat(Qt.TextFormat.PlainText)
        self._signals_layout.addWidget(self._no_signals)
        self._rules_count = QLabel("")
        self._rules_count.setObjectName("rulesChecked")
        self._rules_count.setTextFormat(Qt.TextFormat.PlainText)
        self._signals_layout.addWidget(self._rules_count)
        layout.addWidget(self._signals_box)

        export_title = QLabel("EXPORT")
        export_title.setObjectName("sectionTitle")
        layout.addWidget(export_title)

        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        self._json_btn = self._make_button("Export JSON", "exportJsonBtn")
        self._csv_btn = self._make_button("Export CSV", "exportCsvBtn")
        export_row.addWidget(self._json_btn)
        export_row.addWidget(self._csv_btn)
        export_row.addStretch(1)
        layout.addLayout(export_row)

        investigation_title = QLabel("INVESTIGATION")
        investigation_title.setObjectName("sectionTitle")
        layout.addWidget(investigation_title)

        investigation_row = QHBoxLayout()
        investigation_row.setSpacing(8)
        self._timeline_btn = self._make_button("View Timeline", "timelineBtn")
        self._tree_btn = self._make_button("Process Tree", "processTreeBtn")
        investigation_row.addWidget(self._timeline_btn)
        investigation_row.addWidget(self._tree_btn)
        investigation_row.addStretch(1)
        layout.addLayout(investigation_row)

        self._status = QLabel("")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._save_btn.clicked.connect(self._on_save_clicked)
        self._check_btn.clicked.connect(self._on_check_clicked)
        self._json_btn.clicked.connect(lambda: self._on_export_clicked("json"))
        self._csv_btn.clicked.connect(lambda: self._on_export_clicked("csv"))
        self._timeline_btn.clicked.connect(self._on_timeline_clicked)
        self._tree_btn.clicked.connect(self._on_tree_clicked)

        self._baseline: BaselineSnapshot | None = None
        self._report: DriftReport | None = None
        self._operation_busy = False
        self._exporting = False
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

    def set_baseline(self, baseline: BaselineSnapshot | None) -> None:
        """Adopt a baseline (or clear it). Drift state resets with it:
        a fresh baseline invalidates the previous report honestly.
        Any in-flight operation lock is released — a completed save is
        what called us."""
        self._operation_busy = False
        self._exporting = False
        self._baseline = baseline
        self._report = None
        if baseline is None:
            self._baseline_label.setText("Baseline: Not set")
        else:
            self._baseline_label.setText(f"Baseline: {_fmt_when(baseline.created_at)}")
        self._checked_label.setText("Last checked: —")
        self._drift_summary.setText("No drift check yet")
        self._unverified.hide()
        self._render_signals(None)
        self._refresh_buttons()

    def show_drift(self, report: DriftReport, heuristics: HeuristicReport) -> None:
        """Render a completed drift check: summary, unverified note, signals."""
        self._operation_busy = False
        self._exporting = False
        self._report = report
        self._checked_label.setText(f"Last checked: {_fmt_when(report.compared_at)}")
        self._drift_summary.setText(f"{len(report.events)} change(s) detected")
        if report.unverified_categories:
            self._unverified.setText(
                f"Could not verify: {', '.join(report.unverified_categories)}"
            )
            self._unverified.show()
        else:
            self._unverified.hide()
        self._render_signals(heuristics)
        self._refresh_buttons()

    # ------------------------------------------------------------------
    # Operation lifecycle (in-progress and result states)
    # ------------------------------------------------------------------

    def set_save_busy(self, busy: bool) -> None:
        self._set_operation_busy(busy, "Reading a fresh baseline…")

    def set_check_busy(self, busy: bool) -> None:
        self._set_operation_busy(busy, "Checking for drift…")

    def set_export_busy(self, busy: bool) -> None:
        self._exporting = busy
        self._refresh_buttons()
        if busy:
            self._show_status("Exporting…")

    def show_save_failed(self, message: str) -> None:
        self._operation_busy = False
        self._exporting = False
        self._show_status(f"Baseline save failed: {message}", warn=True)
        self._refresh_buttons()

    def show_drift_failed(self, message: str) -> None:
        self._operation_busy = False
        self._exporting = False
        self._show_status(f"Drift check failed: {message}", warn=True)
        self._refresh_buttons()

    def show_export_result(self, success: bool, message: str) -> None:
        self._exporting = False
        self._operation_busy = False
        self._show_status(message, warn=not success)
        self._refresh_buttons()

    def show_export_cancelled(self) -> None:
        self._show_status("Export cancelled.")

    def _set_operation_busy(self, busy: bool, message: str) -> None:
        self._operation_busy = busy
        self._refresh_buttons()
        if busy:
            self._show_status(message)

    def _show_status(self, text: str, warn: bool = False) -> None:
        self._status.setText(text)
        self._status.setObjectName("statusWarn" if warn else "muted")
        style = self._status.style()
        style.unpolish(self._status)
        style.polish(self._status)

    # ------------------------------------------------------------------
    # Signals rendering
    # ------------------------------------------------------------------

    def _render_signals(self, heuristics: HeuristicReport | None) -> None:
        """Render the signals list, or an explicit empty/not-checked state."""
        while self._signals_layout.count() > 2:
            item = self._signals_layout.takeAt(2)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if heuristics is None:
            self._no_signals.setText("Not checked yet")
            self._no_signals.show()
            self._rules_count.setText("")
            self._rules_count.hide()
            return
        signals = heuristics.signals
        if not signals:
            self._no_signals.setText("No suspicious signals detected")
            self._no_signals.show()
            self._rules_count.setText(f"{len(heuristics.rules_applied)} rules checked")
            self._rules_count.show()
            return
        self._no_signals.hide()
        self._rules_count.hide()
        for signal in signals:
            self._signals_layout.addWidget(self._make_signal_row(signal))

    def _make_signal_row(self, signal) -> QWidget:
        row = QWidget()
        row.setObjectName("signalRow")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(1)

        head = QHBoxLayout()
        severity = QLabel(signal.severity)
        severity.setObjectName("signalSeverity")
        severity.setTextFormat(Qt.TextFormat.PlainText)
        if signal.severity == SEVERITY_MEDIUM:
            severity.setProperty("level", "elevated")
        elif signal.severity == SEVERITY_HIGH:
            severity.setProperty("level", "high")
        else:
            severity.setObjectName("muted")
        entity = QLabel(signal.entity)
        entity.setObjectName("signalEntity")
        entity.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(severity)
        head.addWidget(entity, 1)
        why_btn = QPushButton("Why?")
        why_btn.setObjectName("secondary")
        why_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        why_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        why_btn.setToolTip("Show the evidence facts behind this signal")
        why_btn.clicked.connect(lambda checked=False, s=signal: self.why_requested.emit(s))
        head.addWidget(why_btn)
        row_layout.addLayout(head)

        reason = QLabel(signal.reason)
        reason.setObjectName("signalReason")
        reason.setWordWrap(True)
        reason.setTextFormat(Qt.TextFormat.PlainText)
        row_layout.addWidget(reason)
        return row

    # ------------------------------------------------------------------
    # Click handlers + button policy
    # ------------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        if self._operation_busy or self._exporting:
            return
        self.save_requested.emit()

    def _on_check_clicked(self) -> None:
        if self._operation_busy or self._exporting or self._baseline is None:
            return
        self.check_requested.emit(self._baseline)

    def _on_export_clicked(self, kind: str) -> None:
        if self._operation_busy or self._exporting or self._report is None:
            return
        self.export_requested.emit(kind)

    def _on_timeline_clicked(self) -> None:
        if self._operation_busy or self._exporting or self._report is None:
            return
        self.timeline_requested.emit()

    def _on_tree_clicked(self) -> None:
        if self._operation_busy or self._exporting or self._report is None:
            return
        self.process_tree_requested.emit()

    def _refresh_buttons(self) -> None:
        busy = self._operation_busy or self._exporting
        self._save_btn.setEnabled(not busy)
        self._check_btn.setEnabled(self._baseline is not None and not busy)
        self._json_btn.setEnabled(self._report is not None and not busy)
        self._csv_btn.setEnabled(self._report is not None and not busy)
        # Investigation views need a completed drift check (timeline data);
        # the tree additionally needs a process sample, which MainWindow
        # guards when opening the dialog.
        self._timeline_btn.setEnabled(self._report is not None and not busy)
        self._tree_btn.setEnabled(self._report is not None and not busy)