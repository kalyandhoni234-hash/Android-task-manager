"""Diagnostics dialog: local log access and diagnostic export.

Phase-1 observability UI, kept deliberately small: it shows the current
diagnostic log file, opens its folder in the system file manager, and
exports a local diagnostic report to a destination the user chooses. All
data stays on the machine — there is no upload and no telemetry.

Follows the existing dialog conventions (IncidentDialog): a read-only
viewer owned by the MainWindow, lazily created and reused, with status
feedback rendered in the dialog itself.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.diagnostics import export_diagnostics, log_file_path

#: Default export filename suggested in the save dialog.
_DEFAULT_EXPORT_NAME = "android-task-manager-diagnostics.txt"


class DiagnosticsDialog(QDialog):
    """Local diagnostics viewer: log path, open folder, export report."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnostics")
        self.setModal(False)
        self.setMinimumWidth(560)

        heading = QLabel("Diagnostics")
        heading.setObjectName("pageTitle")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        subtitle = QLabel(
            "Application diagnostics are stored locally on this computer. "
            "Nothing is ever uploaded."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        subtitle.setTextFormat(Qt.TextFormat.PlainText)

        log_caption = QLabel("Log file")
        log_caption.setObjectName("cardCaption")
        log_caption.setTextFormat(Qt.TextFormat.PlainText)
        self._log_path = QLabel("")
        self._log_path.setObjectName("caption")
        self._log_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._log_path.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._open_btn = QPushButton("Open Log Folder")
        self._open_btn.setObjectName("secondary")
        self._export_btn = QPushButton("Export Diagnostic Log...")
        self._export_btn.setObjectName("secondary")
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primary")
        buttons.addWidget(self._open_btn)
        buttons.addWidget(self._export_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        self._status = QLabel("")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addWidget(log_caption)
        layout.addWidget(self._log_path)
        layout.addSpacing(4)
        layout.addLayout(buttons)
        layout.addWidget(self._status)

        self._open_btn.clicked.connect(self.open_log_folder)
        self._export_btn.clicked.connect(self.export_log)
        close_btn.clicked.connect(self.accept)

        self.refresh()

    # ------------------------------------------------------------------
    # State entry points (MainWindow calls these on the GUI thread)
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the current log file location (e.g. after setup changes)."""
        self._log_path.setText(str(log_file_path()))
        self._status.setText("")

    def open_log_folder(self) -> None:
        """Open the log file's folder in the system file manager."""
        folder = log_file_path().parent
        if not folder.exists():
            self._status.setText(
                f"The log folder does not exist yet: {folder}."
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self._status.setText("Could not open the log folder.")

    def export_log(self) -> None:
        """Export the local diagnostic report to a user-chosen file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Diagnostic Log",
            _DEFAULT_EXPORT_NAME,
            "Text file (*.txt);;All files (*)",
        )
        if not path:
            self._status.setText("Export cancelled.")
            return
        try:
            written = export_diagnostics(path)
        except OSError as exc:
            self._status.setText(f"Export failed: {exc}")
            return
        self._status.setText(f"Exported diagnostic report to {written}.")

    @staticmethod
    def default_export_name() -> str:
        """The suggested export filename (tests)."""
        return _DEFAULT_EXPORT_NAME

    @staticmethod
    def current_log_path() -> Path:
        """The log path currently shown (tests)."""
        return log_file_path()